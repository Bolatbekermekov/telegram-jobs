# Дизайн: авто-отклик на внешние формы (external-apply autofill)

- **Дата:** 2026-07-14
- **Статус:** утверждён (brainstorming), готов к плану
- **Область:** `sender/` (локальная рассылка), затрагивает канал `linkedin`
- **Связано:** [[linkedin-russian-ui]], [[multi-platform-outreach]], `2026-07-06-hh-patchright-platform-design.md`

## 1. Проблема

Поиск LinkedIn (и вообще выдача) даёт **в основном внешние отклики**: у вакансии нет
Easy Apply, есть кнопка «Отправить заявку» / «Apply», которая уводит на сайт компании
(внешний ATS). Сегодня `sender/app/infrastructure/channels/linkedin.py::easy_apply_via_page`
на такой вакансии **осознанно кидает** `ChannelError("внешний отклик LinkedIn ... нужен
ручной отклик")` (строки 138-141), и многошаговый Easy Apply тоже (147-149). Дальше
`SendOutreach.execute` ловит это как ошибку → лид пропускается, приходит уведомление.
Поскольку почти все LinkedIn-вакансии такие, отклик практически не идёт.

**Цель:** вместо пропуска — перейти по внешней кнопке, распознать тип страницы и по
возможности заполнить форму ИИ и отправить (полный автомат с guardrail'ами), а
непроходимое честно пропустить с уведомлением.

## 2. Разведка реальных примеров (каноничные кейсы = будущие фикстуры)

Проверено вживую 2026-07-14 (только чтение структуры, ничего не отправлялось):

| Ссылка | Что на самом деле | Маршрут |
|---|---|---|
| join.com (Lemvos) | ATS, но форма за **email + reCAPTCHA** («Continue with Google») | `gated` |
| ddrive.tech | **Формы нет**, «Apply» = `mailto:hr@ddrive.tech` | `email` |
| superplay.co | Реальная форма во **встроенном iframe Comeet**; на самой странице только куки-чекбоксы | `iframe_ats` |

Вывод: сайты структурно разные → правильный подход не «адаптер под бренд», а
**универсальный филлер, читающий структуру + роутер**. Полностью автономно «нажал и
отправил» невозможно для заметной доли (reCAPTCHA/логин), поэтому ветка «отдать вручную» —
обязательная часть, а не костыль.

## 3. Ключевые решения (из брейншторма)

1. **Стратегия:** универсальный ИИ-филлер + fallback (роутер классифицирует страницу).
2. **Отправка:** полный автомат (`Submit` сразу), но с guardrail'ами, не требующими клика
   пользователя (см. §9).
3. **Данные:** структурный `sender/apply_profile.yml`; факты берутся оттуда
   детерминированно, свободные вопросы — ИИ; чего нет и что `required` → **не отправляем**;
   EEO/демография → «Prefer not to say».

## 4. Non-goals (YAGNI)

- Не решаем CAPTCHA, не создаём аккаунты в ATS, не проходим логин/верификацию почты — это
  ветка `gated` (скип + пинг).
- Не пишем per-ATS адаптеры под конкретные бренды (кроме распознавания известных iframe-ATS
  по домену для ветки `iframe_ats`).
- Не трогаем многошаговый LinkedIn Easy Apply в MVP (опциональная Фаза 4).
- Не делаем UI подтверждения перед отправкой (выбран полный автомат).

## 5. Архитектура

Ложится на существующую гексагональную структуру `sender/app` (`domain` → `application` →
`infrastructure`). Грязный Playwright изолирован в одном модуле; вся логика решений — чистая
и тестируемая без браузера и сети (как `hh_questions.py`).

| Слой | Файл | Роль |
|---|---|---|
| domain | `domain/apply_profile.py` | dataclass `ApplyProfile` (каноничные факты кандидата) |
| domain | `domain/page_observation.py` | dataclass `PageObservation` (сериализуемый снимок формы) + `Route` enum |
| application | `application/classify_apply.py` | **чистый классификатор** `classify(obs) -> Route` |
| application | `application/auto_apply.py` | маппинг «поле → факт профиля», сборка `ApplyPlan`, флаг `ready_to_submit` |
| application | `application/hh_questions.py` *(обобщить)* | готовые `parse_ai_answers` / `fill_plan` — переиспользуем как есть |
| infrastructure | `infrastructure/apply_profile_loader.py` | загрузка `apply_profile.yml` (+ `.example`, gitignore) |
| infrastructure | `infrastructure/channels/external_apply.py` | Playwright-драйвер: `scrape_form`, вход в iframe/новую вкладку, заполнение, `Submit`, `verify`, детект гейта |
| — | `channels/linkedin.py` *(правка)* | `easy_apply_via_page`: внешний отклик → хэндофф в `external_apply` |
| — | `config.py` *(правка)* | `APPLY_DRY_RUN`, `APPLY_PROFILE_PATH`, `EXTERNAL_APPLY_ENABLED` |

Драйвер строится по образцу `headhunter.py::apply_via_page`: **`answerer` инжектируется как
callable** `answerer(questions, vacancy_context) -> answers`, поэтому браузер и OpenAI не
попадают в чистую логику. Роль `answerer` играет
`OpenAIMessageGenerator.answer_questions` (уже существует).

## 6. Классификатор — сердце фичи (чистая функция)

`PageObservation` (то, что уже прототипировалось в разведке; он же — форма тест-фикстуры):

```
PageObservation:
  url: str
  form_count: int
  fields: list[FieldObs]          # {tag, type, label, name, required, options_count}
  file_inputs: int
  iframes: list[str]              # src каждого iframe
  mailto_links: list[str]
  apply_buttons: list[str]        # видимые тексты apply-кнопок/ссылок
  captcha: bool                   # маркер recaptcha/hcaptcha/turnstile
  login_required: bool            # поле пароля + «create account/register/sign in»
  text_excerpt: str               # первые ~240 симв. body
```

`classify(obs) -> Route`, порядок проверок важен:

1. **Игнорировать «нереальные» поля.** Отфильтровать consent/cookie/gdpr-чекбоксы и
   поисковые поля по label/name (regex `cookie|consent|gdpr|search`). Это прямой урок
   superplay, где видимые поля — только куки.
2. `captcha == True` **или** `login_required == True` (нужны для доступа к форме) → **`gated`**.
3. Есть «реальные» apply-поля (email / имя / `input[type=file]` / textarea, не куки) →
   **`form`**.
4. Есть iframe известного ATS (`comeet.co`, `greenhouse.io`, `lever.co`, `ashbyhq.com`,
   `workable.com`, `smartrecruiters.com`, `teamtailor.com`, `recruitee.com`) → **`iframe_ats`**
   (вернуть src фрейма).
5. Есть `mailto`-отклик и формы нет → **`email`**.
6. Иначе → **`none`**.

Ожидаемая классификация фикстур: join.com → `gated`, ddrive.tech → `email`,
superplay.co → `iframe_ats`.

## 7. Поток данных (LinkedIn → внешний отклик)

1. `LinkedInChannel.send(job_url)` → `linkedin_action_for_url == "easy_apply"` →
   `easy_apply_via_page`.
2. Есть `button.jobs-apply-button` и одношаговый → существующий Easy Apply (без изменений).
3. Нет Easy Apply → это внешний отклик. Если основное действие — `mailto:` → сразу ветка
   `email` (**не** кликаем).
4. Иначе клик по «Отправить заявку»/«Apply». Внешний отклик часто открывает **новую
   вкладку** — драйвер ловит popup (`context.expect_page`) и работает с новой страницей.
5. `scrape_form(page)` → `PageObservation` → `classify` → ветка:
   - **`email`** → извлечь адрес из `mailto` + сгенерить subject/body (`OpenAIMessageGenerator`)
     + приложить CV → отдать **готовому `email_channel`**.
   - **`iframe_ats`** → перейти во фрейм (frame-локатор) или напрямую по его src → пере-скрейп
     → как `form`.
   - **`gated`** → `ManualApplyRequired` (скип + пинг; при `headless=false` можно оставить
     вкладку открытой).
   - **`form`** → дальше.
   - **`none`** → скип + пинг.
6. `AutoApply.build_plan(obs, profile, job_context)` → `ApplyPlan`:
   - детерминированно из профиля: email, телефон, имя, город/страна, LinkedIn/GitHub/портфолио,
     право на работу, виза, зарплата (маппинг label/name → ключ профиля, см. §8);
   - `input[type=file]` → путь к CV (`cv_loader`);
   - свободные вопросы (textarea/«why»/cover letter) → `answerer` (ИИ) через `fill_plan`;
   - `ready_to_submit == False`, если любое `required`-поле не замаплено или содержит
     `[плейсхолдер]`.
7. Если `not ready_to_submit` → **скип + уведомление** (лид остаётся `new`).
8. Иначе `fill_and_submit`: заполнить поля/чекбоксы/селекты, загрузить CV; если **не**
   `APPLY_DRY_RUN` → клик `Submit` → `verify_submitted`. Соблюсти паузу (`MIN/MAX_DELAY`) и
   дневной лимит (`DAILY_SEND_LIMIT`).
9. Результат → `SendResult` → статус в таблице + Telegram-уведомление.

## 8. Данные кандидата — `sender/apply_profile.yml`

Gitignored, рядом кладём `apply_profile.yml.example`. Схема:

```yaml
full_name: ""
first_name: ""
last_name: ""
email: ""
phone: ""              # с кодом страны, напр. +7...
city: ""
country: ""
linkedin: ""
github: ""
portfolio: ""
work_authorization: "" # напр. "Authorized to work in Kazakhstan / remote"
needs_visa_sponsorship: false
desired_salary: ""     # свободный текст, напр. "from $2000/mo"
open_to_relocation: false
notice_period: ""      # напр. "2 weeks"
custom_answers:        # ключ-фраза (lowercase substring) -> готовый ответ
  "years of experience": "3"
  "why do you want": ""   # пусто -> ответит ИИ по CV+profile.md
```

Правила заполнения:
- Факт из профиля есть → пишем детерминированно.
- Поле свободное и в `custom_answers` нет/пусто → ИИ (`answerer`), без выдумок (правило
  «ничего не выдумывай» уже в `profile.md`).
- EEO/демография (пол, раса, ветеран, инвалидность) → выбрать «Prefer not to say» / пропустить.
- `required` и данных нет → `ready_to_submit = False` → скип.

## 9. Guardrail'ы полного автомата (не требуют клика)

- **Не жать `Submit`**, если есть незаполненное `required`-поле или остался `[плейсхолдер]`
  → скип + пинг (зеркалит текущую защиту от плейсхолдеров в письмах).
- **Гейт** (reCAPTCHA/логин/регистрация) → не пытаться.
- **`verify_submitted`** после отправки (по образцу hh) — подтвердить, что заявка ушла.
- **`APPLY_DRY_RUN=true`** — заполнить и залогировать/сфоткать, что *отправил бы*, но
  **не** жать `Submit` (для первых прогонов).
- **Лимиты и паузы** — переиспользуем `DAILY_SEND_LIMIT`, `MIN/MAX_DELAY_SECONDS`.
- **`_check_not_blocked`-аналог** → `RateLimitedError` при явной блокировке.

## 10. Ошибки и статусы

- Новый `ManualApplyRequired(ChannelError)` по образцу `InvitePendingError`: не хард-фейл, а
  отдельный исход. `SendResult` расширяем полем `manual: bool` (как `invited`); маппинг
  `SendResult → статус/уведомление` (там же, где обрабатывается `invited`) добавляет статус
  `manual` и пинг с URL, чтобы можно было доотправить руками.
- Неполные данные/плейсхолдер → скип, лид остаётся `new` (повтор позже).
- `email`-ветка при успехе → обычный `sent` (ушло через email-канал).

## 11. Config / env (добавить в `config.py`)

```
EXTERNAL_APPLY_ENABLED = env "true"      # рубильник всей фичи
APPLY_DRY_RUN          = env "false"     # true = заполнить, но не Submit
APPLY_PROFILE_PATH     = env -> sender/apply_profile.yml
```
Переиспользуются: `BROWSER_HEADLESS`, `DAILY_SEND_LIMIT`, `MIN/MAX_DELAY_SECONDS`, `CV_PATH`,
`OPENAI_*`. Документировать в `.env.example` и в README (раздел «Платформы»).

## 12. Что НЕ строим заново (reuse map)

| Нужно | Готовое |
|---|---|
| Ответы на свободные вопросы | `application/hh_questions.py` (`parse_ai_answers`/`fill_plan`) |
| ИИ-ответчик | `OpenAIMessageGenerator.answer_questions` |
| Сопроводительное | `OpenAIMessageGenerator.generate` |
| email-отклик (ветка `email`) | `infrastructure/channels/email_channel.py` |
| CV-файл | `infrastructure/cv_loader.py` / `config.CV_PATH` |
| Инъекция `answerer` в драйвер | паттерн `headhunter.apply_via_page(..., answerer=...)` |
| Лимиты/паузы/уведомления/статусы | текущий send-flow + `SendResult` + `telegram_notify` |

## 13. Тестирование

**Юниты (offline, всегда в CI) — TDD:**
- `classify()` на записанных `PageObservation`-фикстурах трёх реальных сайтов →
  ассертим `gated` / `email` / `iframe_ats`; плюс синтетика на `form` (Greenhouse-подобная)
  и `none`; плюс проверка фильтрации куки-полей (кейс superplay).
- `AutoApply.build_plan`: маппинг label → ключ профиля; `ready_to_submit=False` при
  отсутствии `required`; EEO → «Prefer not to say».
- `apply_profile_loader`: парсинг YAML, дефолты, отсутствующий файл.
- Драйвер `external_apply` — тонкий, тестируется с **фейковым `page`** (как текущие
  linkedin-тесты).

**Живой тест на реальных ссылках (по требованию пользователя) — `sender/tests/live/`,
opt-in (`@pytest.mark.live`, не в CI; запуск `make apply_probe`):**
- Навигация Playwright на три реальные ссылки → `scrape_form` → `classify` → **ассерт
  маршрута** для каждой (join.com=`gated`, ddrive=`email`, superplay=`iframe_ats`), и для
  `form`/`iframe_ats` — что `build_plan` собирается без падения.
- **Безопасность теста (критично):** тест гоняется в режиме **классификации/`DRY_RUN`** —
  `Submit` НЕ нажимается, реальным работодателям (Lemvos/DataDrive/SuperPlay) ничего не
  отправляется. Это проверка распознавания и заполнения, а не подачи.
- Помечен как flaky (сеть, анти-бот, сайты меняются) → не блокирует CI; ссылки вынесены в
  конфиг теста, чтобы легко заменить, когда вакансии закроются.

## 14. Фазы (MVP → дальше)

- **Фаза 1:** `PageObservation` + `classify` + ветка `form` + `gated`/`none` (скип+пинг) +
  `apply_profile.yml` + `APPLY_DRY_RUN` + хэндофф из `linkedin.py`. Юнит-тесты классификатора
  и маппера. Покрывает Greenhouse/Lever/Ashby/Workable/SmartRecruiters-подобные.
- **Фаза 2:** ветка `email` (mailto → `email_channel`) — дёшево, реюз.
- **Фаза 3:** ветка `iframe_ats` (Comeet/эмбеды) + живой тест на трёх ссылках.
- **Фаза 4 (опц.):** многошаговый LinkedIn Easy Apply тем же движком.

## 15. Риски и допущения

- **Хрупкость селекторов** — универсальный скрейп по типам/лейблам устойчивее бренд-адаптеров,
  но новые виджеты (кастомные дропдауны, «add another», date-picker) могут не заполниться →
  `ready_to_submit=False` → безопасный скип.
- **Бан аккаунта** — как и по всей рассылке: только с домашнего IP, дневной лимит, паузы;
  риск принят пользователем (см. README).
- **Отправка неверных данных** — снижается детерминированным профилем + скипом при неполноте;
  `APPLY_DRY_RUN` для обкатки.
- **Новая вкладка / cross-origin iframe** — штатно поддержано Playwright, но требует аккуратной
  обработки в драйвере.
```
