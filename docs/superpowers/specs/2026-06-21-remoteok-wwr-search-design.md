# Design: добавление площадок RemoteOK и We Work Remotely

Дата: 2026-06-21

## Цель

Добавить две новые площадки поиска вакансий в существующий пайплайн
`telegram-jobs`:

- **RemoteOK** (`remoteok.com`)
- **We Work Remotely** (`weworkremotely.com`)

Обе — remote-first, worldwide, без логина и без Cloudflare. В отличие от
LinkedIn/Wellfound, забираются по **чистому HTTP** (без браузера).

## Принципы

- Новые площадки ведут себя **единообразно** с LinkedIn/Wellfound: те же
  `SEARCH_KEYWORDS`, тот же AI-порог `MATCH_THRESHOLD = 60`, тот же
  `SEARCH_LIMIT_PER_PLATFORM`.
- Каждая площадка — отдельный `Searcher` с тем же интерфейсом, что у
  `LinkedInSearcher`. Никаких изменений в `run_search` не требуется — новые
  площадки «бесплатно» подхватываются существующим пайплайном
  (dedup → AI-оценка → запись в «Кандидаты»).
- **Дедупликация до AI-оценки.** `run_search` уже отбрасывает кандидатов с
  известными URL (`candidates_repo.known_urls()`) **до** вызова `describe()` и
  скоринга. Новые площадки наследуют это автоматически. Для WWR это критично:
  `describe()` там — отдельный сетевой запрос, и дедуп-до-скоринга экономит и
  сеть, и токены AI. Требование: `describe()` вызывается только для уже
  отфильтрованных (новых) URL — никаких сетевых вызовов и токенов на повторы.
- Парсинг (превращение сырого JSON/HTML в `Candidate`) изолирован в чистых
  функциях и покрыт юнит-тестами на зафиксированных образцах. Сетевой ввод-вывод
  — тонкая обёртка, в юнит-тестах не дёргается.

## Интерфейс Searcher (контракт)

Каждый новый searcher реализует:

- `name: str` — ключ платформы (`"remoteok"` / `"wwr"`).
- `start() -> None` — для HTTP-площадок no-op (нет браузера/сессии).
- `stop() -> None` — no-op.
- `search(keywords_list, location, limit) -> list[Candidate]`.
- `describe(url) -> str` — текст описания вакансии (для AI-оценки).

`Candidate` (см. `sender/app/domain/candidate.py`) заполняется:
`platform`, `kind=KIND_JOB`, `url`, `title`, `company`, `salary`, `location`,
`summary`.

## 1. RemoteOK (`sender/app/infrastructure/search/remoteok_search.py`)

- Источник: JSON API `https://remoteok.com/api`.
  - Требуется заголовок `User-Agent` (дефолтный python-UA может блокироваться).
  - **Первый элемент** массива — юридический дисклеймер, его пропускаем.
- `search(keywords_list, location, limit)`:
  - Один GET всей свежей ленты.
  - Фильтр по ключевикам: совпадение (регистронезависимо) в `position`/title,
    `tags` или `description`. Вакансия проходит, если матчит **любой** ключевик.
  - `summary` и `salary` берём прямо из JSON (поля `description`,
    `salary_min`/`salary_max`); `location` из поля `location`.
  - Бюджет: общий `limit` на площадку (как у остальных). `location` из конфига
    игнорируется по смыслу (доска и так remote-worldwide).
- `describe(url)`: возвращает уже сохранённое из JSON описание для этого url —
  **без второго сетевого запроса** (ноль лишних трат на загрузку и AI).
  Реализация: searcher держит словарь `url -> description`, собранный в `search()`.
- `start()/stop()`: no-op.

### Парсинг (чистые функции, тестируемые)

- `parse_remoteok_jobs(payload: list) -> list[dict]` — отбрасывает дисклеймер,
  нормализует поля.
- `job_matches(job: dict, keywords: list[str]) -> bool` — фильтр по ключевикам.
- `to_candidate(job: dict) -> Candidate` — маппинг в доменную сущность.

## 2. We Work Remotely (`sender/app/infrastructure/search/wwr_search.py`)

- Источник: поиск
  `https://weworkremotely.com/remote-jobs/search?term=<keyword>` — по каждому
  ключевику отдельно.
- Зависимость: лёгкий HTML-парсер `beautifulsoup4` (добавляется в requirements).
- `search(keywords_list, location, limit)`:
  - `per_keyword_limit(limit, len(keywords_list))` — как у LinkedIn/Wellfound.
  - Для каждого ключевика: GET страницы поиска, парсим карточки списка
    (title, company, относительный url → абсолютный).
  - `salary`/`location`/`summary` со страницы списка обычно недоступны →
    оставляем `""` (AI-оценка подтянет описание через `describe()`).
- `describe(url)`: GET страницы вакансии, вытаскиваем блок описания
  (`section.listing-container` / основной контент), обрезаем до 6000 символов.
- `start()/stop()`: no-op.

### Парсинг (чистые функции, тестируемые)

- `parse_wwr_cards(html: str) -> list[Candidate]` — карточки из страницы поиска.
- `parse_wwr_description(html: str) -> str` — описание со страницы вакансии.

## 3. Точки интеграции

| Место | Изменение |
|---|---|
| `sender/app/infrastructure/search/registry.py` | два новых `case` в `build_searcher` |
| `sender/app/domain/search_request.py` | `SEARCH_PLATFORMS += ["remoteok", "wwr"]` (входят в авто-поиск `all`) |
| `sender/app/application/search_commands.py` | `platforms_arg`: токены `search_remoteok`, `search_wwr` |
| `sender/run.py` | dispatch новых токенов |
| `sender/register_bot_menu.py` | команды `/search_remoteok`, `/search_wwr` |
| `intake-bot/app/domain/bot_commands.py` | `command_to_search_platform`: `remoteok`/`wwr` |
| `intake-bot/app/infrastructure/candidates_gateway.py` | `_BADGE`: `🟢 RemoteOK`, `🟧 WWR` |
| `Makefile` | цели `search_remoteok`, `search_wwr` |
| `requirements` (sender) | `beautifulsoup4` |
| `sender/app/domain/candidate.py` | комментарий `platform:` обновить (linkedin/wellfound/remoteok/wwr) |
| конфиг (`config.py`) | опц.: `HTTP_USER_AGENT`, `REMOTEOK_API_URL`, `WWR_BASE_URL` с дефолтами |

## 4. Обработка ошибок

- Сетевой сбой/таймаут одной площадки **не валит остальные** — уже обеспечено
  `on_error` и `try/finally` в `run_search`.
- RemoteOK: 429 / пустой или не-JSON ответ → логируем, площадка возвращает `[]`,
  остальные работают.
- WWR: ошибка на отдельной вакансии в `describe()` → площадка её пропускает
  (паттерн как в `score_and_filter`: исключение на одной карточке не роняет
  весь прогон).
- Таймауты HTTP-запросов задаём явно (напр. 20 c), чтобы прогон не зависал.

## 5. Тестирование (TDD)

Юнит-тесты на зафиксированных образцах (без сети):

- `test_remoteok_search.py`: `parse_remoteok_jobs` отбрасывает дисклеймер;
  `job_matches` по title/tags/description; `to_candidate` маппинг полей.
- `test_wwr_search.py`: `parse_wwr_cards` из образца HTML поиска;
  `parse_wwr_description` из образца HTML вакансии.
- Интеграция платформ: `search_commands`/`bot_commands` распознают новые токены;
  `SEARCH_PLATFORMS` содержит обе площадки.

Все существующие тесты (sender + intake-bot) остаются зелёными.

## Вне рамок (YAGNI)

- Пагинация/глубокий обход лент (берём свежий срез под лимит).
- Серверный keyword-поиск RemoteOK (фильтруем на своей стороне — надёжнее).
- Профили/рекрутеры (`KIND_PROFILE`) — только вакансии.
