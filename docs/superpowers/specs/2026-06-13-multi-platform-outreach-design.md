# Мультиплатформенная отправка (под-проект B)

**Дата:** 2026-06-13
**Статус:** дизайн на согласовании

## Контекст

Сейчас sender умеет рассылать outreach только в Telegram от имени аккаунта
пользователя (`TelethonMessenger`). Архитектура уже построена по принципу
«порт + адаптер»: use-case `SendOutreach` работает с абстрактным `messenger`,
у которого есть метод `.send(nickname, text, attachment_path)`.

Цель под-проекта B — обобщить отправку на пять платформ, чтобы за **один
запуск** sender прошёл по всем лидам в Google Sheet и для каждого выбрал
нужный канал по колонке «Платформа».

Это первый из трёх под-проектов. Не входит в B (отдельные spec'и позже):
- **A** — авто-определение платформы/цели из текста при приёме (intake-бот).
- **C** — автопоиск вакансий LinkedIn/Wellfound и автоотклик.

## Поддерживаемые платформы

| Платформа | Тип цели | Транспорт | Авторизация |
|---|---|---|---|
| Telegram | DM по @нику/ссылке | Telethon (есть) | `.session`-файл |
| LinkedIn | DM / connection note по URL профиля | Playwright | сохранённая сессия браузера |
| HeadHunter | отклик на вакансию (URL/ID) | официальный API (httpx) | OAuth token + refresh |
| Email | письмо на адрес | SMTP (smtplib) | host/user/app-password |
| Wellfound | отклик на вакансию (URL) | Playwright | сохранённая сессия браузера |

Различие «написать человеку» vs «откликнуться на вакансию» инкапсулировано
**внутри адаптера**. Use-case об этом не знает: он просто отдаёт каналу `target`
и контент.

## Архитектура

### Порт `OutreachChannel`

Новый протокол (`sender/app/domain/channel.py`), который реализует каждый адаптер:

```python
class OutreachChannel(Protocol):
    name: str                  # "telegram" | "linkedin" | "hh" | "email" | "wellfound"
    body_limit: int | None     # лимит символов тела (LinkedIn note = 300), None = без лимита
    needs_subject: bool        # True для email

    def start(self) -> None: ...   # логин / инициализация сессии
    def stop(self) -> None: ...
    def send(self, target: str, content: OutreachContent) -> None: ...
```

```python
@dataclass
class OutreachContent:
    body: str
    subject: str | None = None
    attachment_path: str | None = None
```

`send` бросает исключение при ошибке (как сейчас Telethon); use-case ловит его
и превращает в `SendResult` — поведение `SendOutreach` не меняется.

### Адаптеры

Новый пакет `sender/app/infrastructure/channels/`:

- `telegram.py` — текущий `TelethonMessenger`, переименованный/обёрнутый под
  порт. `body_limit=None`, `needs_subject=False`. Логика нормализации @ника
  переезжает сюда без изменений.
- `linkedin.py` — Playwright с persistent context (`storage_state.json`).
  `start()` при отсутствии валидной сессии открывает окно браузера для ручного
  логина один раз. `send()` идёт по URL профиля → отправляет сообщение
  (или connection note, если не в контактах). `body_limit=300`.
- `headhunter.py` — httpx-клиент к официальному API hh.ru. `send()` =
  отклик (`negotiation`) на вакансию по ID/URL с сопроводительным письмом и
  привязанным резюме. `body_limit` по лимиту API сопроводительного.
- `email.py` — smtplib. `send()` шлёт письмо с темой и CV во вложении.
  `needs_subject=True`, `body_limit=None`.
- `wellfound.py` — Playwright, аналогично LinkedIn; `send()` = отклик на
  вакансию с сообщением.

### Реестр каналов

`sender/app/infrastructure/channels/registry.py`:

```python
def build_channel(platform: str, config) -> OutreachChannel
def enabled_platforms(config) -> set[str]   # какие каналы сконфигурированы в .env
```

Каналы создаются **лениво**: поднимается только тот канал, для платформы
которого реально есть лиды и есть конфиг. Неизвестная/несконфигурированная
платформа → лид помечается `skipped` с заметкой, отправка не падает.

## Модель данных

`Lead` (`sender/app/domain/lead.py`) получает поля:
- `platform: str` — значение из колонки «Платформа».
- `target: str` — значение из колонки «Цель» (ник / URL профиля / URL вакансии / email).

Поле `nickname` упраздняется в пользу `target`; Telegram-адаптер берёт `target`.

Google Sheet: добавляются колонки **Платформа** и **Цель**. Константа `COLUMNS`
обновляется. ВАЖНО: `COLUMNS` дублируется в intake-боте
(`google-apps-script/Formatting.gs` и `intake-bot`); порядок колонок должен
совпадать. Синхронизация — пункт плана реализации. На время B intake может
проставлять `platform="telegram"` по умолчанию (полноценная детекция — это A).

`SheetsRepo` (`fetch_new_leads`, `mark_*`) читает/пишет новые колонки.

## Генерация контента

`GenerateMessage` остаётся платформо-независимым и отдаёт **базовое тело**
сообщения (как сейчас: AI-тело + подпись из `signature.txt`).

Адаптация под платформу — отдельный шаг **перед** `send()`:
- усечение тела до `channel.body_limit`, если задан (LinkedIn 300), без обрезки
  подписи/ссылок на полуслове;
- для `needs_subject` каналов (email) генерируется короткая тема письма
  (отдельный вызов AI или эвристика из вакансии — детали в плане).

Where this lives: новый маленький компонент `format_for_channel(channel, body) ->
OutreachContent` в `sender/app/application/` либо метод канала. Решается в плане.

## Цикл отправки (CLI)

`cli.run()` обобщается:
1. Прочитать новых лидов.
2. Сгруппировать по `platform`; поднять только нужные каналы (`channel.start()`).
3. Для каждого лида: сгенерировать тело → `format_for_channel` → выбрать канал
   из реестра → `SendOutreach.execute(lead, content)` → обновить статус.
4. Анти-бан пауза и **дневной лимит — на каждую платформу отдельно**
   (особенно важно для LinkedIn). Конфиг: `DAILY_SEND_LIMIT` становится
   per-platform (можно через `DAILY_SEND_LIMIT_LINKEDIN` и т.п. с дефолтом).
5. `finally`: остановить все поднятые каналы.

Ручной/AUTO режимы (`AUTO_SEND`) сохраняются как есть.

## Конфигурация

`config.py` расширяется блоками per-platform, все опциональны (канал включён,
если его секция заполнена):
- Telegram — как сейчас.
- LinkedIn / Wellfound — путь к `storage_state.json`, флаг headless.
- HeadHunter — `HH_CLIENT_ID/SECRET`, путь к файлу токена, ID резюме.
- Email — `SMTP_HOST/PORT/USER/PASSWORD`, `FROM_NAME`.
- Per-platform дневные лимиты и задержки (дефолт от общих значений).

`.env.example` обновляется.

## Обработка ошибок

- Per-lead `try/except → SendResult` — уже есть, сохраняется.
- Канал не сконфигурирован / неизвестная платформа → лид `skipped` + заметка,
  цикл продолжается.
- Browser-сессия протухла (LinkedIn/Wellfound) → понятная ошибка «перелогинься»;
  лид `failed`.
- Детект rate-limit/бана в browser-адаптере → канал поднимает специальное
  исключение; цикл останавливает **эту** платформу, оставшиеся её лиды →
  `skipped`, другие платформы продолжают.

## Тестирование

- Use-case `SendOutreach` — тест с fake-каналом (паттерн уже есть в
  `test_send.py`), проверка маппинга `target`/контента и обработки исключения.
- Каждый адаптер — юнит-тесты с моками транспорта: mock Playwright `page`
  (LinkedIn/Wellfound), mock httpx (HH), mock smtplib (Email), Telethon — как
  сейчас.
- Контрактный тест: каждый адаптер из реестра удовлетворяет `OutreachChannel`
  и не отдаёт тело длиннее `body_limit`.
- `format_for_channel` — тесты усечения по лимиту и генерации темы.

## Вне scope B (явно)

- Авто-определение платформы из текста (это A).
- Поиск вакансий и автоотклик-воркфлоу LinkedIn/Wellfound (это C).
- Антибот-обход/капчи на LinkedIn сверх ручного логина и человекоподобных пауз.

## Открытые вопросы для плана реализации

1. Точный эндпоинт hh.ru для отклика и привязки резюме (сверить по официальному
   API в момент реализации).
2. Где живёт `format_for_channel` — отдельный use-case или метод канала.
3. Стратегия per-platform лимитов: общий счётчик vs отдельные env-переменные.
