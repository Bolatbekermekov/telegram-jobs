# HH (hh.ru) как полноценная платформа: поиск + отклики через patchright

Дата: 2026-07-06
Статус: утверждено (дизайн v2, согласован в сессии)

## Зачем

hh.ru закрыл соискательский API 15 декабря 2025 — существующий канал
`sender/app/infrastructure/channels/headhunter.py` (POST `api.hh.ru/negotiations`
с `HH_ACCESS_TOKEN`) мёртв, а заявки на dev.hh.ru соискателям больше не одобряют.
Единственный рабочий путь — UI-автоматизация браузером. В проекте уже есть
проверенный паттерн: Wellfound работает через patchright (стелс-Playwright,
`channel="chrome"`) с сохранённой сессией.

HH встраивается в существующий конвейер без его изменения:

```
/search_hh (бот)  ─┐
/start_search (бот)├→ вкладка «Команды» → worker → HHSearcher → вкладка «Кандидаты»
make search[_hh]  ─┘                                                │
                                              Telegram: ✅ Approve / ❌ Скип
                                                                    │
                                              approve → главная вкладка (status=new)
                                                                    │
                              make send → HeadHunterChannel → отклик на hh.ru
```

## Не-цели (YAGNI)

- Никаких изменений в approve-конвейере, worker'е, CLI-циклах — HH только
  регистрируется как ещё одна платформа.
- Без выбора резюме в модалке отклика: HH подставляет резюме по умолчанию
  (у пользователя одно). Если появится второе — отдельная задача.
- Без обхода капчи: капча = стоп платформы, решается вручную.
- Без пагинации глубже 2 страниц поиска.

## 1. Один логин: `make login_hh`

- Новая Makefile-цель `login_hh` (по образцу `login_wellfound`).
- Открывает patchright-Chrome (headful) на `https://hh.ru/account/login`,
  пользователь логинится вручную (SMS-код), скрипт ждёт `input()` и сохраняет
  `context.storage_state(path=HH_STATE_PATH)`.
- `HH_STATE_PATH` — новый конфиг, дефолт `<root>/sender/hh_state.json`
  (рядом с `wellfound_state.json`; уже покрыт маской `*_state.json`
  в `.gitignore` — ничего добавлять не нужно).
- И серчер, и канал читают этот же файл: логин один раз, дальше молча.
- Если state отсутствует: у **канала** — ручной логин-фолбэк с `input()`,
  как в `WellfoundChannel.start()` (рассылка интерактивна); у **серчера** —
  `RuntimeError` с подсказкой `make login_hh` (worker работает без присмотра
  и не должен блокироваться на `input()`).

## 2. Поиск: `HHSearcher`

Файл: `sender/app/infrastructure/search/hh_search.py`.

- patchright sync API, `channel="chrome"`, headful по умолчанию
  (`BROWSER_HEADLESS` уважается, но для HH рекомендован headful — антибот).
- `search(query)` → goto `https://hh.ru/search/vacancy?text=<query>` (+ фильтры
  при необходимости позже), собрать карточки с 1–2 страниц: title, company,
  vacancy URL. DOM-логика в модульной функции
  `parse_results_page(page) -> list[...]`, тестируемой фейковой страницей.
- Возвращает кандидатов в том же формате, что RemoteOK/Remotive/WWR-серчеры →
  дальше существующий путь: AI-релевантность → вкладка «Кандидаты».
- Регистрация:
  - `SEARCH_PLATFORMS` (`sender/app/domain/search_request.py`): + `"hh"`;
  - `build_searcher` (`sender/app/infrastructure/search/registry.py`): ветка `"hh"`;
  - бот: `command_to_search_platform` (`intake-bot/app/domain/bot_commands.py`):
    `/search_hh` → `"hh"`; `/start_search` подхватит автоматически;
  - Makefile: цель `search_hh`.
- Селекторы снимаются с живой страницы hh.ru (Playwright snapshot) до
  кодирования, не по памяти.

## 3. Отправка: новый `HeadHunterChannel`

Файл: `sender/app/infrastructure/channels/headhunter.py` — полная замена.

- Сохраняется `extract_vacancy_id(target)` (лиды бывают голым id и ссылкой);
  канал строит URL `https://hh.ru/vacancy/<id>`.
- `apply_via_page(page, vacancy_url, content)` — модульная функция, вся
  DOM-логика в ней (паттерн `wellfound.apply_via_page`):
  1. `goto(vacancy_url)`;
  2. если на странице «Вы откликнулись» → `ChannelError("already applied")`
     (лид уходит в failed с понятной причиной, платформа продолжает);
  3. кнопка «Откликнуться»; нет кнопки → `ChannelError`;
  4. в форме отклика: раскрыть сопроводительное («Добавить сопроводительное»
     или сразу textarea), `fill(content.body)`, кнопка отправки;
  5. редирект на логин / страница капчи → `RateLimitedError` — CLI
     останавливает платформу HH целиком, остальные лиды не сжигаются.
- `HeadHunterChannel`:
  - `name="hh"`, `body_limit=10000` (лимит сопроводительного HH),
    `needs_subject=False`;
  - `__init__(storage_state_path, headless=False)`;
  - `start()`/`stop()` — как у `WellfoundChannel` (patchright, chrome-канал,
    storage_state, логин-фолбэк);
  - `send(target, content)` → `apply_via_page`.

## 4. Конфиг и регистрация

`sender/app/config.py`:
- удалить `HH_ACCESS_TOKEN`, `HH_RESUME_ID`;
- добавить `HH_STATE_PATH` (дефолт `<root>/sender/hh_state.json`);
- `platform_enabled("hh")` → `True` (браузерный логин интерактивен, как
  linkedin/wellfound).

`sender/app/infrastructure/channels/registry.py`:
- `build_channel("hh")` → `HeadHunterChannel(config.HH_STATE_PATH, config.BROWSER_HEADLESS)`.

README: секция про HH-токен заменяется на «один раз `make login_hh`».

## 5. Анти-бан

Существующие механизмы применяются как есть: `DAILY_SEND_LIMIT` (20/день на
платформу), случайные паузы `MIN/MAX_DELAY_SECONDS`, ручное подтверждение
каждого сообщения. Автоматизация hh.ru нарушает ToS — риск бана аккаунта
принят пользователем (тот же принцип, что для Telegram/Wellfound/LinkedIn,
задокументирован в README).

## 6. Тестирование (TDD)

Фейковые страницы, ни одного реального браузера в юнит-тестах:

- `test_headhunter_channel.py` — переписать: `_FakePage` (образец —
  `test_wellfound_channel.py`): успешный отклик (goto → click → fill → submit),
  «уже откликнулся» → `ChannelError`, редирект на логин → `RateLimitedError`,
  метаданные канала; оставить тесты `extract_vacancy_id`.
- `test_hh_search.py` — новый: `parse_results_page` на фейковой странице,
  формат кандидатов.
- Обновить: `test_registry.py` (`_Cfg` без токенов, с `HH_STATE_PATH`),
  `test_channel_contract.py` (новый конструктор),
  `test_config_platforms.py` (`platform_enabled("hh") is True`),
  `test_search_platforms.py` (+`"hh"`), `test_search_registry.py`,
  `test_bot_menu_platforms.py` / тест `command_to_search_platform` (+`/search_hh`).
- Ручная проверка после реализации: `make login_hh`, `make search_hh`,
  отклик на одну реальную вакансию через `make send`.

## Порядок реализации

1. Логин + канал отправки (конфиг, `HeadHunterChannel`, registry, тесты).
2. Серчер (`HHSearcher`, SEARCH_PLATFORMS, registry, тесты).
3. Интеграция: бот `/search_hh`, Makefile (`login_hh`, `search_hh`), README.
4. Снятие реальных селекторов hh.ru через Playwright и ручная E2E-проверка.
