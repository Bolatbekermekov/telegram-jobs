# Threads как источник вакансий — Implementation Plan (Фаза 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ссылка на тред в Threads становится полноценным лидом: интейк сохраняет его сразу, ноут дочитывает весь тред автора, находит настоящий контакт и отправляет существующим каналом, а DM в Threads остаётся fallback'ом.

**Architecture:** Ленивый резолв. `intake-bot` (Vercel, только httpx) распознаёт URL поста и кладёт лид с текстом из `og:description`. `sender` (ноут, patchright) перед генерацией сообщения рендерит тред **анонимно**, склеивает корневой пост с самоответами автора, прогоняет детект контакта по полному тексту и перезаписывает платформу лида — после чего лид уходит уже существующим `telegram`/`email` каналом. Новый `ThreadsChannel` на отдельной (burner) сессии используется только когда контакта в треде нет.

**Tech Stack:** Python 3.10+ (venv на 3.14.6), httpx, patchright/playwright 1.55, gspread, pytest.

**Спек:** `docs/superpowers/specs/2026-07-26-threads-source-and-typed-outreach-design.md`

**Фаза 2 (классификатор вакансия/проект, два системных промпта, расслоение `profile.md`, клавиша `t`) — отдельный план, пишется после того как Фаза 1 сольётся.**

**Одно осознанное исключение из «без заглушек».** `ThreadsChannel._deliver` (Task 9) поднимается `NotImplementedError` и получает реальную реализацию в Task 10 Step 9. Причина: DOM DM-композера невозможно снять без залогиненного аккаунта, а весь остальной DOM в этой фиче снят живьём 2026-07-26 и зашит в код. Придумывать селекторы, которых не видел, хуже, чем отложить их на шаг, где есть сессия. Фаза 1 при этом остаётся полезной без этого шага: главный путь (найти контакт в треде и отправить существующим каналом) работает целиком, а лид без контакта получает статус `manual` с заметкой — допустимый по спеку исход, и это **не** `skipped`.

## Global Constraints

- **Threads читается только не-браузерным непустым User-Agent.** Браузерный UA (`_UA` в `vacancy_fetcher.py`), пустой UA и UA соц-краулеров (`facebookexternalhit`, `Twitterbot`, `TelegramBot`, `Slackbot`) получают SPA-скелет без og-тегов. Рабочие: `curl/*`, `python-httpx/*`, `Python-urllib/*`, `python-requests/*`, произвольный `vacancy-intake-bot/1.0`, `Googlebot`. Проверено живьём 2026-07-26.
- **`og:description` = только корневой пост.** Самоответов автора в анонимном HTML нет вообще. Полный тред доступен только через рендер.
- **Лид никогда не теряется.** Инвариант из коммита `e2edb49`.
- **Никакого авто-`skipped`.** Ни резолвер, ни канал не имеют права молча похоронить лид. Терминальный статус при проблеме сессии — `manual`, а не `skipped`.
- **Резолвер рендерит анонимно**, без `storage_state`. Чтение публичной страницы не должно касаться burner-сессии и не несёт риска бана. Сессия нужна только `ThreadsChannel`.
- **Самоответы автора определяются сравнением username, а не бейджем «Автор»** — бейдж локализован (`Автор` / `Author`).
- **Значения-константы английские при русских заголовках колонок** — как существующие `STATUS_*` и `KIND_JOB`.
- **Домен дублируется между приложениями осознанно.** `sender` получает своё `app/domain/contact.py`; общий пакет не заводим (так же уже раздвоены `sheets_repo.py` и `lead.py`).
- Тесты sender: `make test-unit` (то есть `sender/.venv/bin/python -m pytest sender/tests -v -m "not live"`).
- Тесты intake: `sender/.venv/bin/python -m pytest intake-bot/tests -v` (у intake нет своего venv; системный python3 — 3.9 и не умеет `X | None`). Базовая линия на 2026-07-26: **83 passed**. Если падает сбор `test_webhook_search.py` с `No module named 'fastapi'` — доставить: `uv pip install --python sender/.venv/bin/python "fastapi==0.115.6"` (версия из `intake-bot/requirements.txt`; в venv нет `pip`, только uv).
- Базовая линия sender на 2026-07-26: `make test-unit` → **377 passed, 3 deselected**.
- **Три самых хитрых блока прогнаны до написания плана и проходят:** чистка мусора треда (Task 5, 12/12), детект контакта в интейке вместе со всеми существующими тестами приоритетов (Task 1, 29/29), зеркало детекта в sender (Task 4, 14/14). Регулярки и JS-селекторы в плане — снятые с живой страницы, а не предположения. Если тест из плана падает — это расхождение с реальностью, разбирайся с причиной, а не ослабляй тест.

## File Structure

**intake-bot** (Vercel, только httpx, без браузера):

| Файл | Ответственность |
|---|---|
| `app/domain/contact.py` (M) | распознавание и канонизация URL поста Threads, правило в `detect_contact` |
| `app/domain/vacancy_text.py` (M) | `extract_threads_post` — текст поста из `og:description` |
| `app/infrastructure/vacancy_fetcher.py` (M) | per-site User-Agent + ветка Threads |
| `api/webhook.py` (M) | ответ бота для threads-лида |
| `tests/fixtures/threads/*.html` (C) | реальная разметка: пост, отсутствующий пост, SPA-скелет |

**sender** (ноут, patchright):

| Файл | Ответственность |
|---|---|
| `app/domain/contact.py` (C) | зеркало детекта контакта, без правила threads |
| `app/domain/threads_post.py` (C) | **чистая** сборка треда: чистка мусора, фильтр по автору |
| `app/infrastructure/threads_thread.py` (C) | **тонкий** DOM-ридер + анонимный рендер |
| `app/infrastructure/threads_session.py` (C) | жива ли сохранённая сессия Threads |
| `app/infrastructure/channels/threads.py` (C) | `ThreadsChannel` — DM автору |
| `app/application/resolve_threads_lead.py` (C) | рендер → детект → перезапись лида |
| `app/domain/lead.py` (M) | `COL_PLATFORM` / `COL_TARGET` / `COL_VACANCY` |
| `app/infrastructure/sheets_repo.py` (M) | `update_resolved` — одна атомарная запись |
| `app/infrastructure/channels/registry.py` (M) | ветка `threads` |
| `app/config.py` (M) | `THREADS_STATE_PATH`, `platform_enabled` |
| `app/application/login.py` (M) | `LOGIN_ORDER` |
| `app/interface/cli.py` (M) | `_KNOWN`, хук резолвера, `run_login_threads`, `run_login_all` |
| `run.py`, `Makefile` (M) | команда `login_threads` |

Границы намеренно проведены так, что **вся логика сборки треда чистая и полностью тестируемая** (`app/domain/threads_post.py`), а DOM-специфичное изолировано в одном тонком файле — тем же принципом, что уже записан в шапке `channels/linkedin.py` («DOM interaction is isolated … because selectors drift»).

---

### Task 1: Интейк — распознавание и канонизация URL Threads

**Files:**
- Modify: `intake-bot/app/domain/contact.py`
- Test: `intake-bot/tests/test_detect_contact.py`

**Interfaces:**
- Produces: `canonical_threads_url(url: str) -> str`, `threads_author(url: str) -> str` (возвращает `"@handle"` или `""`), и `Contact("threads", <канонический URL>)` из `detect_contact`.

> **Правка от 2026-07-26 (по итогам ревью Task 1):** `threads_post_id` из плана
> **удалён**. Его никто не вызывает — Task 6 разбирает автора самостоятельно
> (`author_from_url`), а дедуп в явных не-целях. Держать неиспользуемую функцию
> «на потом» противоречит YAGNI из этого же плана. Канонизация к id остаётся
> описанной в спеке как свойство URL, но отдельной функции под неё нет.

- [ ] **Step 1: Написать падающие тесты**

Добавить в конец `intake-bot/tests/test_detect_contact.py`:

```python
# --- Threads --------------------------------------------------------------

from app.domain.contact import canonical_threads_url, threads_author  # noqa: E402

_SHARED = ("https://www.threads.com/@lnkrnchk/post/DbL4LxBl6v9"
           "?xmt=AQG0bheD9uqmoSjOr9bFyIfWrZmjZK8OWTtZ0RjfvAVPAHs981VOMdhda3xuSsAZwsdDgJA"
           "&slof=1")
_CLEAN = "https://www.threads.com/@lnkrnchk/post/DbL4LxBl6v9"


def test_threads_post_is_detected():
    c = detect_contact(_CLEAN)
    assert c == Contact("threads", _CLEAN)


def test_threads_share_tracking_is_dropped():
    """The share sheet appends ?xmt=…&slof=1; the sheet must hold a plain URL."""
    assert detect_contact(_SHARED).target == _CLEAN


def test_threads_net_is_folded_onto_threads_com():
    c = detect_contact("вакансия https://www.threads.net/@lnkrnchk/post/DbL4LxBl6v9")
    assert c.target == _CLEAN


def test_threads_without_scheme_or_www():
    assert detect_contact("threads.com/@lnkrnchk/post/DbL4LxBl6v9").target == _CLEAN


def test_threads_url_author_is_not_read_as_a_telegram_handle():
    """The '@' in the URL path is preceded by '/', so _HANDLE_RE must not fire."""
    assert detect_contact(_CLEAN).platform == "threads"


def test_a_real_telegram_handle_still_beats_a_threads_link():
    c = detect_contact(f"Пиши @ivan_hr по вакансии {_CLEAN}")
    assert c == Contact("telegram", "@ivan_hr")


def test_the_threads_authors_own_handle_does_not_hijack_the_lead():
    """"вакансия от @lnkrnchk <ссылка>" must stay threads: that handle is the post
    author, not a Telegram user, and DMing it would reach nobody."""
    c = detect_contact(f"вакансия от @lnkrnchk {_CLEAN}")
    assert c.platform == "threads"


def test_email_in_the_message_still_beats_a_threads_link():
    c = detect_contact(f"{_CLEAN} резюме на hr@acme.com")
    assert c.platform == "email"


def test_threads_helpers():
    assert canonical_threads_url(_SHARED) == _CLEAN
    assert threads_author(_SHARED) == "@lnkrnchk"
    assert threads_author("https://hh.ru/vacancy/1") == ""
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

Run: `sender/.venv/bin/python -m pytest intake-bot/tests/test_detect_contact.py -v -k threads`
Expected: FAIL — `ImportError: cannot import name 'canonical_threads_url'`

- [ ] **Step 3: Реализовать**

В `intake-bot/app/domain/contact.py` после блока `_WELLFOUND_RE` добавить:

```python
# Threads (Meta). Posts live at /@user/post/<id>. threads.net is an alias that
# 301s to threads.com (verified 2026-07-26: identical bytes), so it is folded onto
# .com — the sender opens exactly what the sheet holds. The iOS/Android share sheet
# appends a tracking blob (?xmt=…&slof=1) that is noise for us.
_THREADS_HOST = r"(?:www\.)?threads\.(?:com|net)"
_THREADS_RE = re.compile(
    rf"(?:https?://)?{_THREADS_HOST}/@[\w.]+/post/[\w-]+\S*", re.IGNORECASE)
_THREADS_PARTS_RE = re.compile(
    rf"^(?:https?://)?{_THREADS_HOST}/@([\w.]+)/post/([\w-]+)", re.IGNORECASE)


def canonical_threads_url(url: str) -> str:
    """A shared Threads link -> the plain post URL the sender can open."""
    m = _THREADS_PARTS_RE.match(url)
    if not m:
        return url
    return f"https://www.threads.com/@{m.group(1)}/post/{m.group(2)}"


def threads_author(url: str) -> str:
    """'@handle' of the post author from the URL, or '' when it is not a Threads
    post link. Authoritative author comes from the rendered page in the sender;
    this is what the intake has to work with."""
    m = _THREADS_PARTS_RE.match(url)
    return "@" + m.group(1) if m else ""
```

Затем заменить тело `detect_contact` целиком:

```python
def detect_contact(text: str) -> Contact | None:
    # The Threads link is located up front, but only to protect its author handle:
    # "вакансия от @lnkrnchk <threads link>" would otherwise match _HANDLE_RE and
    # be stored as a Telegram contact, and the send loop would DM a user that does
    # not exist there. A DIFFERENT @handle still wins, as it always did.
    tm = _THREADS_RE.search(text)
    threads_url = canonical_threads_url(_clean(tm.group(0))) if tm else ""

    m = _TME_RE.search(text)
    if m:
        return Contact("telegram", _clean(m.group(0)))
    m = _HANDLE_RE.search(text)
    if m and ("@" + m.group(1)).lower() != threads_author(threads_url).lower():
        return Contact("telegram", "@" + m.group(1))
    m = _EMAIL_RE.search(text)
    if m:
        return Contact("email", m.group(0))
    m = _LINKEDIN_RE.search(text)
    if m:
        return Contact("linkedin", _clean(m.group(0)))
    m = _HH_VACANCY_RE.search(text) or _HH_RE.search(text)
    if m:
        return Contact("hh", canonical_hh_url(_clean(m.group(0))))
    m = _WELLFOUND_RE.search(text)
    if m:
        return Contact("wellfound", _clean(m.group(0)))
    if threads_url:
        return Contact("threads", threads_url)
    return None
```

Обновить docstring модуля (строки 3-5): порядок приоритетов теперь
`telegram > email > linkedin > hh > wellfound > threads`, и приписать, что threads идёт
последним намеренно — ссылка на тред вместе с @ником рекрутера должна оставаться telegram.
Обновить комментарий поля `platform` в `Contact` — добавить `threads`.

- [ ] **Step 4: Запустить тесты и убедиться, что всё проходит**

Run: `sender/.venv/bin/python -m pytest intake-bot/tests/test_detect_contact.py -v`
Expected: PASS — все тесты, включая существующие (регресса приоритетов быть не должно).

- [ ] **Step 5: Коммит**

```bash
git add intake-bot/app/domain/contact.py intake-bot/tests/test_detect_contact.py
git commit -m "feat(intake): распознавать ссылку на пост Threads как контакт"
```

---

### Task 2: Интейк — чтение текста поста + реальные фикстуры

**Files:**
- Modify: `intake-bot/app/domain/vacancy_text.py`
- Create: `intake-bot/tests/fixtures/threads/post.html`, `intake-bot/tests/fixtures/threads/missing.html`, `intake-bot/tests/fixtures/threads/spa_shell.html`
- Test: `intake-bot/tests/test_vacancy_text.py`

**Interfaces:**
- Consumes: ничего из Task 1.
- Produces: `extract_threads_post(html: str, max_chars: int = 5000) -> str` — сигнатура один-в-один как у существующей `extract_linkedin_post`.

- [ ] **Step 1: Создать фикстуры из живых страниц**

> **Правка от 2026-07-26 (по итогам ревью Task 2): скрипт ниже был неверен.** Он
> скачивал настоящие ответы, проверял их assert'ами и затем **записывал вместо них
> синтетические 76 байт**, из-за чего `missing.html` и `spa_shell.html` получались
> байт-в-байт одинаковыми: два теста кормили один блоб и утверждали одно и то же под
> разными именами. Это нарушало требование самого же спека — фикстуры должны быть
> настоящей разметкой с живого сайта. Правильная версия: все три фикстуры —
> **усечённые срезы реальных ответов** (первые 30 000 байт, чтобы попал `<head>` и
> кусок скриптов), и скрипт захвата **коммитится** рядом с ними как
> `intake-bot/tests/fixtures/threads/capture.py`, чтобы доказательство живого
> поведения было воспроизводимым. Источник истины — этот закоммиченный скрипт, а не
> текст ниже.

Запустить ровно этот скрипт из корня проекта:

```bash
mkdir -p intake-bot/tests/fixtures/threads
sender/.venv/bin/python - <<'PY'
import re, pathlib, urllib.request

OUT = pathlib.Path("intake-bot/tests/fixtures/threads")
POST = "https://www.threads.com/@lnkrnchk/post/DbL4LxBl6v9"

def get(url, ua):
    req = urllib.request.Request(url, headers={"User-Agent": ua})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read().decode("utf-8", "replace")

# A non-browser UA gets the server-rendered page that carries og:*.
raw = get(POST, "python-httpx/0.27.0")
metas = re.findall(
    r'<meta[^>]+(?:property|name)="(?:og:[a-z]+|description|twitter:description)"[^>]+>', raw)
assert metas, "og-тегов нет: Threads отдал скелет, проверь UA"
(OUT / "post.html").write_text(
    "<!DOCTYPE html><html><head>\n" + "\n".join(metas) + "\n</head><body></body></html>",
    encoding="utf-8")

# A deleted / non-existent post id: the page comes back 200 with NO og tags at all.
missing = get("https://www.threads.com/@lnkrnchk/post/ZZZZZZZZZZZ", "python-httpx/0.27.0")
assert not re.search(r'property="og:description"', missing), "у отсутствующего поста появился og"
(OUT / "missing.html").write_text(
    "<!DOCTYPE html><html><head><title>Threads</title></head><body></body></html>",
    encoding="utf-8")

# A browser UA gets a JS shell — the trap this whole feature has to avoid.
shell = get(POST, "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
assert not re.search(r'property="og:description"', shell), "браузерный UA неожиданно отдал og"
(OUT / "spa_shell.html").write_text(
    "<!DOCTYPE html><html><head><title>Threads</title></head><body></body></html>",
    encoding="utf-8")

for f in sorted(OUT.iterdir()):
    print(f, f.stat().st_size, "bytes")
PY
```

Expected: три файла; `post.html` ≈ 5 КБ, остальные ≈ 90 байт.
Если `assert` падает — Threads поменял отдачу; **останови задачу и сообщи**, не подгоняй тесты.

- [ ] **Step 2: Написать падающие тесты**

Добавить в конец `intake-bot/tests/test_vacancy_text.py`:

```python
# --- Threads posts --------------------------------------------------------

from pathlib import Path  # noqa: E402

from app.domain.vacancy_text import extract_threads_post  # noqa: E402

_FX = Path(__file__).parent / "fixtures" / "threads"


def test_threads_post_text_comes_from_og_description():
    text = extract_threads_post((_FX / "post.html").read_text(encoding="utf-8"))
    assert text.startswith("Ищу Full Stack Developer")
    assert "Lovable" in text
    assert len(text) == 480          # og:description caps the root post here


def test_threads_missing_post_yields_nothing():
    """A deleted/non-existent post returns a page with no og tags at all."""
    assert extract_threads_post((_FX / "missing.html").read_text(encoding="utf-8")) == ""


def test_threads_spa_shell_yields_nothing_not_garbage():
    """What a browser User-Agent gets. Must be empty, never partial junk."""
    assert extract_threads_post((_FX / "spa_shell.html").read_text(encoding="utf-8")) == ""


def test_threads_empty_html():
    assert extract_threads_post("") == ""


def test_threads_entities_are_decoded_and_newlines_kept():
    html = ('<meta property="og:description" content="Ищем&#064;QA&amp;Dev'
            '&#10;&#8212; тесты" />')
    text = extract_threads_post(html)
    assert "@" in text and "&" in text and "&amp;" not in text
    assert "\n" in text


def test_threads_respects_max_chars():
    html = '<meta property="og:description" content="' + "a" * 900 + '" />'
    assert len(extract_threads_post(html, max_chars=100)) == 100
```

- [ ] **Step 3: Запустить тесты и убедиться, что они падают**

Run: `sender/.venv/bin/python -m pytest intake-bot/tests/test_vacancy_text.py -v -k threads`
Expected: FAIL — `ImportError: cannot import name 'extract_threads_post'`

- [ ] **Step 4: Реализовать**

Добавить в конец `intake-bot/app/domain/vacancy_text.py`:

```python
# A Threads post's text lives in og:description, like a LinkedIn post's — but with
# two differences that matter (both verified live 2026-07-26):
#
#  * Threads serves that markup ONLY to a non-browser User-Agent. A browser UA gets
#    a JS shell with no og tags at all, so the fetcher must NOT send `_UA` here.
#  * og:description carries the ROOT post only, capped around 480 chars. The rest of
#    the vacancy and the contact to apply to live in the author's self-replies, which
#    are absent from the anonymous HTML entirely. The sender re-reads the whole thread
#    in a browser; this is the cheap first pass that lets intake answer instantly.
#
# No boilerplate filter is needed (LinkedIn needs `_LI_POST_BOILERPLATE_RE`): a
# deleted or private Threads post comes back with no og tags, so it falls out here.
# Match og:description specifically, not `(?:og:)?description` — the page also carries
# a shorter plain `description` and a `twitter:description`, and relying on document
# order to pick the right one is a coin flip.
_TH_OG_DESC_RE = re.compile(
    r'<meta[^>]+property="og:description"[^>]+content="([^"]*)"', re.IGNORECASE)


def extract_threads_post(html: str, max_chars: int = 5000) -> str:
    """Text of a Threads post from its og:description ("" when absent)."""
    if not html:
        return ""
    m = _TH_OG_DESC_RE.search(html)
    if not m:
        return ""
    # Already plain text: decode entities and keep the line breaks (they separate
    # the post's bullet points), don't collapse whitespace.
    text = _html.unescape(m.group(1)).strip()
    return text[:max_chars] if text else ""
```

- [ ] **Step 5: Запустить тесты и убедиться, что всё проходит**

Run: `sender/.venv/bin/python -m pytest intake-bot/tests/test_vacancy_text.py -v`
Expected: PASS

- [ ] **Step 6: Коммит**

```bash
git add intake-bot/app/domain/vacancy_text.py intake-bot/tests/test_vacancy_text.py \
        intake-bot/tests/fixtures/threads
git commit -m "feat(intake): читать текст поста Threads из og:description"
```

---

### Task 3: Интейк — per-site User-Agent, ветка фетчера и ответ бота

**Files:**
- Modify: `intake-bot/app/infrastructure/vacancy_fetcher.py`
- Modify: `intake-bot/api/webhook.py:238-242` (ветка `except ValueError`) и `:230-234` (успешный ответ)
- Test: `intake-bot/tests/test_threads_fetch.py` (создать)

**Interfaces:**
- Consumes: `extract_threads_post` из Task 2.
- Produces: `is_threads_post_url(url: str) -> bool`; `_get(url, timeout, attempts=…, sleep=None, ua=_UA)` — новый последний параметр `ua`; `is_fetchable_vacancy_url` теперь принимает и посты Threads.

- [ ] **Step 1: Написать падающий тест**

Создать `intake-bot/tests/test_threads_fetch.py`:

```python
"""Threads is fetched with a NON-browser User-Agent. This is the opposite of hh and
LinkedIn, and getting it wrong returns an empty JS shell — so it is pinned by test."""
from pathlib import Path

import app.infrastructure.vacancy_fetcher as vf

_FX = Path(__file__).parent / "fixtures" / "threads"


def test_recognises_threads_post_urls():
    assert vf.is_threads_post_url("https://www.threads.com/@a/post/DbL4LxBl6v9")
    assert vf.is_threads_post_url("https://threads.net/@a.b/post/Xy-1")
    assert not vf.is_threads_post_url("https://www.threads.com/@a")
    assert not vf.is_threads_post_url("https://hh.ru/vacancy/1")


def test_threads_posts_are_fetchable():
    assert vf.is_fetchable_vacancy_url("https://www.threads.com/@a/post/Db1")


def test_threads_is_fetched_without_the_browser_user_agent(monkeypatch):
    seen = {}

    def fake_get(url, timeout, attempts=2, sleep=None, ua=None):
        seen["ua"] = ua
        return (_FX / "post.html").read_text(encoding="utf-8")

    monkeypatch.setattr(vf, "_get", fake_get)
    text = vf.fetch_vacancy_text("https://www.threads.com/@lnkrnchk/post/DbL4LxBl6v9")

    assert text.startswith("Ищу Full Stack Developer")
    assert seen["ua"] == vf._CLIENT_UA
    assert "Mozilla" not in seen["ua"], "браузерный UA отдаёт пустой SPA-скелет"


def test_hh_and_linkedin_keep_the_browser_user_agent(monkeypatch):
    seen = []
    monkeypatch.setattr(vf, "_get",
                        lambda url, timeout, attempts=2, sleep=None, ua=None:
                        seen.append(ua) or "")
    vf.fetch_vacancy_text("https://hh.ru/vacancy/1")
    vf.fetch_vacancy_text("https://www.linkedin.com/jobs/view/1")
    assert seen == [vf._UA, vf._UA]


def test_get_sends_the_user_agent_it_is_given(monkeypatch):
    captured = {}

    class _Resp:
        status_code = 200
        text = "ok"

    def fake_httpx_get(url, headers=None, timeout=None, follow_redirects=None):
        captured["headers"] = headers
        return _Resp()

    import httpx
    monkeypatch.setattr(httpx, "get", fake_httpx_get)
    assert vf._get("https://x/", 1.0, ua="probe/1.0") == "ok"
    assert captured["headers"]["User-Agent"] == "probe/1.0"
```

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

Run: `sender/.venv/bin/python -m pytest intake-bot/tests/test_threads_fetch.py -v`
Expected: FAIL — `AttributeError: module … has no attribute 'is_threads_post_url'`

- [ ] **Step 3: Реализовать per-site UA**

В `intake-bot/app/infrastructure/vacancy_fetcher.py`:

3a. После определения `_UA` добавить:

```python
# Threads is the exact inverse of hh/LinkedIn: it serves the server-rendered page
# (the one that carries og:description) only to a NON-browser client. Verified live
# 2026-07-26 — a browser UA gets a 258 KB JS shell with no og tags, an EMPTY UA gets
# nothing either, and so do the social-crawler UAs (facebookexternalhit, Twitterbot,
# TelegramBot, Slackbot). Plain HTTP-client UAs work: curl/*, python-httpx/*,
# python-requests/*, Python-urllib/*, Googlebot, and this one.
# Do NOT "unify" the two constants — that silently empties every Threads lead.
_CLIENT_UA = "vacancy-intake-bot/1.0"
```

3b. Добавить регулярку и предикат рядом с остальными:

```python
_THREADS_POST_RE = re.compile(
    r"^https?://(?:www\.)?threads\.(?:com|net)/@[\w.]+/post/[\w-]+", re.IGNORECASE)
```

```python
def is_threads_post_url(url: str) -> bool:
    return bool(_THREADS_POST_RE.match((url or "").strip()))
```

3c. Включить в `is_fetchable_vacancy_url`:

```python
def is_fetchable_vacancy_url(url: str) -> bool:
    return (is_hh_vacancy_url(url) or is_linkedin_job_url(url)
            or is_linkedin_post_url(url) or is_threads_post_url(url))
```

3d. Параметризовать `_get` — заменить сигнатуру и вызов `httpx.get`:

```python
def _get(url: str, timeout: float, attempts: int = _RETRY_ATTEMPTS, sleep=None,
         ua: str = _UA) -> str:
```

```python
            resp = httpx.get(url, headers={"User-Agent": ua}, timeout=timeout,
                             follow_redirects=True)
```

3e. Заменить `fetch_vacancy_text` целиком:

```python
def fetch_vacancy_text(url: str, timeout: float = _TIMEOUT_SECONDS) -> str:
    """Vacancy text behind `url`, or "" if it can't be read for any reason."""
    url = (url or "").strip()
    ua = _UA
    if is_hh_vacancy_url(url):
        extract = extract_hh_vacancy
    elif is_linkedin_job_url(url):
        extract = extract_linkedin_vacancy
    elif is_linkedin_post_url(url):
        extract = extract_linkedin_post
    elif is_threads_post_url(url):
        extract = extract_threads_post
        ua = _CLIENT_UA          # a browser UA gets an empty JS shell here
    else:
        return ""
    try:
        return extract(_get(url, timeout, ua=ua))
    except Exception:  # noqa: BLE001 — never let intake fail over a missing description
        return ""
```

3f. Добавить `extract_threads_post` в импорт из `app.domain.vacancy_text` и дописать в docstring модуля абзац про Threads: SSR только не-браузерному UA, `og:description` = только корневой пост, полный тред дочитывает sender.

- [ ] **Step 4: Запустить тесты и убедиться, что всё проходит**

Run: `sender/.venv/bin/python -m pytest intake-bot/tests -v`
Expected: PASS — весь набор intake, включая существующие тесты фетчера.

- [ ] **Step 5: Обновить ответы бота**

В `intake-bot/api/webhook.py` в успешной ветке (сейчас `f"✅ Сохранил лид\n…"`) добавить приписку для threads. Заменить блок:

```python
        lead = _build_use_case().execute(text)
        extra = ""
        if lead.platform == "threads":
            # Only the root post is readable without a browser; the rest of the
            # vacancy and the contact to apply to sit in the author's self-replies,
            # which the laptop reads at send time.
            extra = ("\n\nℹ️ Пост Threads прочитан частично (только первый пост). "
                     "Полный тред и контакт для отклика дочитаю при отправке с ноута.")
        _reply(
            chat_id,
            f"✅ Сохранил лид\nПлатформа: {lead.platform}\nИсточник: {lead.target}\n"
            f"Вакансия: {lead.vacancy_context}{extra}",
        )
```

И в ветке `except ValueError` дописать Threads в перечисление источников:

```python
        _reply(
            chat_id,
            "⚠️ Не нашёл контакт. Пришли вакансию с одним из: @ник, t.me-ссылка, "
            "email, или ссылка LinkedIn / hh.ru / Wellfound / Threads.",
        )
```

- [ ] **Step 6: Запустить весь набор intake**

Run: `sender/.venv/bin/python -m pytest intake-bot/tests -v`
Expected: PASS

- [ ] **Step 7: Коммит**

```bash
git add intake-bot/app/infrastructure/vacancy_fetcher.py intake-bot/api/webhook.py \
        intake-bot/tests/test_threads_fetch.py
git commit -m "feat(intake): читать пост Threads не-браузерным UA, UA стал per-site"
```

---

### Task 4: Sender — зеркало детекта контакта

**Files:**
- Create: `sender/app/domain/contact.py`
- Test: `sender/tests/test_contact.py`

**Interfaces:**
- Produces: `Contact(platform: str, target: str)` (dataclass) и `detect_contact(text: str) -> Contact | None` в пакете `sender`. Порядок приоритетов `telegram > email > linkedin > hh > wellfound`; правила `threads` здесь **нет**.

- [ ] **Step 1: Написать падающий тест**

Создать `sender/tests/test_contact.py`:

```python
"""Contact detection, sender-side copy. Used by the Threads resolver to find the
real contact inside a rendered thread."""
from app.domain.contact import Contact, detect_contact


def test_telegram_handle():
    assert detect_contact("Пиши @ivan_hr") == Contact("telegram", "@ivan_hr")


def test_telegram_handle_with_a_stray_space_after_the_at():
    """Threads renders a mention as '@ skyluckwalker' — one glued token in the DOM
    text. The real contact must survive that."""
    c = detect_contact("Для отклика присылайте портфолио в Telegram: @ skyluckwalker")
    assert c == Contact("telegram", "@skyluckwalker")


def test_tme_link():
    c = detect_contact("контакт https://t.me/ivanhr")
    assert c.platform == "telegram" and "t.me/ivanhr" in c.target


def test_email():
    assert detect_contact("резюме на hr@acme.com") == Contact("email", "hr@acme.com")


def test_plain_email_is_not_telegram():
    assert detect_contact("john@gmail.com").platform == "email"


def test_linkedin():
    assert detect_contact("linkedin.com/in/ivan").platform == "linkedin"


def test_hh():
    assert detect_contact("https://hh.ru/vacancy/12345").platform == "hh"


def test_regional_hh_is_folded_onto_hh_ru():
    """The saved hh session is hh.ru-only; a regional link dead-ends at the login
    wall. A thread saying "откликнуться на hh.kz/vacancy/…" must not walk into it."""
    c = detect_contact("откликнуться https://astana.hh.kz/vacancy/135297431?from=x")
    assert c.target == "https://hh.ru/vacancy/135297431"


def test_wellfound():
    assert detect_contact("https://wellfound.com/jobs/1-dev").platform == "wellfound"


def test_priority_telegram_over_email():
    assert detect_contact("@ivan_hr или boss@acme.com").platform == "telegram"


def test_none_when_no_contact():
    assert detect_contact("просто описание вакансии") is None


def test_strips_trailing_punctuation():
    assert detect_contact("см. (linkedin.com/in/abc).").target.endswith("abc")
```

- [ ] **Step 2: Запустить тест и убедиться, что он падает**

Run: `sender/.venv/bin/python -m pytest sender/tests/test_contact.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.domain.contact'`

- [ ] **Step 3: Реализовать**

Создать `sender/app/domain/contact.py`:

```python
"""Deterministic detection of (platform, target) from free vacancy text.

Sender-side copy of the intake bot's rule set. The two apps are separate deploys
with their own requirements, and this project already duplicates domain code
across them on purpose (`sheets_repo.py`, `lead.py`) rather than carrying a shared
package — this follows that.

Used by the Threads resolver: a thread's own text is where the real contact lives
("Для отклика присылайте портфолио в Telegram: @skyluckwalker"), and finding it is
what lets a threads lead be sent through the existing Telegram/email channel.

There is deliberately NO `threads` rule here: by the time this runs the lead is
already threads, and the question is only what it should become instead.

Priority order: telegram > email > linkedin > hh > wellfound. Rule-based on
purpose: it decides where the message is sent, so it must not be an LLM guess.
"""
import re
from dataclasses import dataclass


@dataclass
class Contact:
    platform: str   # telegram | email | linkedin | hh | wellfound
    target: str


_TME_RE = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/\w{3,}", re.IGNORECASE)
# `@\s?` because Threads renders a mention with a space after the at-sign, and the
# DOM text comes through as "@ skyluckwalker" — dropping that contact would send the
# lead down the DM fallback for no reason.
_HANDLE_RE = re.compile(r"(?:^|\s)@\s?(\w{4,})\b")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_LINKEDIN_RE = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/\S+", re.IGNORECASE)
_HH_HOST = r"(?:[\w.-]*\.)?hh\.(?:ru|kz|uz|by|kg|az|tj)"
_HH_VACANCY_RE = re.compile(rf"(?:https?://)?{_HH_HOST}/vacancy/\d+\S*", re.IGNORECASE)
_HH_RE = re.compile(rf"(?:https?://)?{_HH_HOST}/\S+", re.IGNORECASE)
_WELLFOUND_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:wellfound\.com|angel\.co)/\S+", re.IGNORECASE)

_TRAILING = ".,);]>\"'"


def _clean(url: str) -> str:
    return url.rstrip(_TRAILING)


_HH_VACANCY_ID_RE = re.compile(rf"^(?:https?://)?{_HH_HOST}/vacancy/(\d+)", re.IGNORECASE)
_HH_REGIONAL_RE = re.compile(
    r"^(?:https?://)?(?:[\w.-]*\.)?hh\.(?:kz|uz|by|kg|az|tj)/", re.IGNORECASE)


def canonical_hh_url(url: str) -> str:
    """A regional HeadHunter link -> the hh.ru URL the saved session can open.

    Kept in this copy on purpose: the browser session from `make login_hh` is
    hh.ru-only, cookies don't cross to a national domain, so a regional link
    browses anonymously and dead-ends at the login wall on Apply. A thread that
    says "откликнуться на hh.kz/vacancy/…" would walk straight into that.
    """
    m = _HH_VACANCY_ID_RE.match(url)
    if m:
        return f"https://hh.ru/vacancy/{m.group(1)}"
    return _HH_REGIONAL_RE.sub("https://hh.ru/", url, count=1)


def detect_contact(text: str) -> Contact | None:
    m = _TME_RE.search(text)
    if m:
        return Contact("telegram", _clean(m.group(0)))
    m = _HANDLE_RE.search(text)
    if m:
        return Contact("telegram", "@" + m.group(1))
    m = _EMAIL_RE.search(text)
    if m:
        return Contact("email", m.group(0))
    m = _LINKEDIN_RE.search(text)
    if m:
        return Contact("linkedin", _clean(m.group(0)))
    m = _HH_VACANCY_RE.search(text) or _HH_RE.search(text)
    if m:
        return Contact("hh", canonical_hh_url(_clean(m.group(0))))
    m = _WELLFOUND_RE.search(text)
    if m:
        return Contact("wellfound", _clean(m.group(0)))
    return None
```

> Порядок правил — **дословно** как в интейке (`telegram > email > linkedin > hh >
> wellfound`). Отличий от интейкового файла ровно два, оба намеренные: `@\s?` в
> `_HANDLE_RE` (Threads рендерит упоминание с пробелом) и отсутствие правила
> `threads`. Не «улучшать» порядок — это копия, и расхождение здесь означало бы,
> что один и тот же текст даёт разный контакт в двух приложениях.

- [ ] **Step 4: Запустить тесты и убедиться, что всё проходит**

Run: `sender/.venv/bin/python -m pytest sender/tests/test_contact.py -v`
Expected: PASS

- [ ] **Step 5: Коммит**

```bash
git add sender/app/domain/contact.py sender/tests/test_contact.py
git commit -m "feat(send): детект контакта на стороне sender для резолва Threads"
```

---

### Task 5: Sender — чистая сборка треда

**Files:**
- Create: `sender/app/domain/threads_post.py`
- Test: `sender/tests/test_threads_post.py`

**Interfaces:**
- Produces:
  - `post_body(parts: list[str]) -> str` — из списка текстов span'ов одного поста убирает мусок интерфейса (бейдж, время, `·`, «Автор», счётчики) и склеивает тело.
  - `author_thread_text(blocks: list[tuple[str, list[str]]], author: str) -> str` — оставляет блоки автора, склеивает их тела через пустую строку.
  - Обе чистые: ни браузера, ни сети.

- [ ] **Step 1: Написать падающие тесты**

Создать `sender/tests/test_threads_post.py`. Данные взяты с живой страницы 2026-07-26 (`https://www.threads.com/@lnkrnchk/post/DbL4LxBl6v9`) — это ровно то, что отдаёт DOM-ридер из Task 6.

```python
"""Pure assembly of a Threads thread. Fixtures are the real span texts read off the
live page 2026-07-26 — including the interface chrome that has to be stripped."""
from app.domain.threads_post import author_thread_text, post_body

# Root post: badge, relative time, body paragraphs, then engagement counters.
ROOT = ["hiring", "1 дн.",
        "Ищу Full Stack Developer (Lovable / Claude Code / AI-first).",
        "Мы развиваем существующий веб-продукт, который преимущественно создан в "
        "Lovable, и ищем разработчика, который использует AI как основной инструмент.",
        "Что предстоит делать:", "— развивать существующий продукт;",
        "— самостоятельно находить технические решения;",
        "32", "14", "16"]

# Author self-reply: same, plus the "·" separator and the localised author badge.
REPLY_1 = ["hiring", "1 дн.", "·", "Автор",
           "— тестировать изменения и доводить задачи до готового результата.",
           "Что важно:", "— опыт современной Full Stack веб-разработки;",
           "Формат работы:", "— full-time, удалённо;", "1", "1"]

# The self-reply that carries the contact.
REPLY_2 = ["hiring", "1 дн.", "·", "Автор",
           "Для отклика присылайте портфолио в Telegram: @ skyluckwalker", "1"]

FOREIGN = ["1 дн.", "Навайбкодили нейрослоп и ищите инженера чтоб с этим разобраться.",
           "3"]


def test_post_body_drops_badge_and_relative_time():
    body = post_body(ROOT)
    assert body.startswith("Ищу Full Stack Developer")
    assert "hiring" not in body
    assert "1 дн." not in body


def test_post_body_drops_engagement_counters():
    body = post_body(ROOT)
    assert body.endswith("— самостоятельно находить технические решения;")
    for n in ("32", "14", "16"):
        assert not body.endswith(n)


def test_post_body_keeps_every_paragraph():
    """The root body is split across several spans; taking only the longest one
    silently dropped the first two paragraphs."""
    body = post_body(ROOT)
    assert "Ищу Full Stack Developer" in body
    assert "Мы развиваем существующий веб-продукт" in body
    assert "Что предстоит делать:" in body


def test_post_body_drops_the_separator_and_author_badge():
    body = post_body(REPLY_1)
    assert body.startswith("— тестировать изменения")
    assert "Автор" not in body and "·" not in body


def test_post_body_survives_an_english_author_badge():
    """The badge is localised; matching on its text would break on an EN account."""
    parts = ["hiring", "1 d", "·", "Author", "Send your portfolio to @ acme_hr", "1"]
    assert post_body(parts) == "Send your portfolio to @ acme_hr"


def test_post_body_of_only_chrome_is_empty():
    assert post_body(["hiring", "1 дн.", "·", "Автор", "1"]) == ""


def test_post_body_of_nothing_is_empty():
    assert post_body([]) == ""


def test_post_body_keeps_a_counter_shaped_line_inside_the_body():
    """A bare number in the MIDDLE is part of the text; only trailing ones are UI."""
    parts = ["1 дн.", "Бюджет проекта:", "5000", "Пишите в личку сюда", "7"]
    body = post_body(parts)
    assert "5000" in body
    assert not body.endswith("7")


def test_author_thread_text_joins_root_and_self_replies_in_order():
    blocks = [("@lnkrnchk", ROOT), ("@lnkrnchk", REPLY_1), ("@lnkrnchk", REPLY_2),
              ("@so_silly_seal", FOREIGN)]
    text = author_thread_text(blocks, "@lnkrnchk")
    assert text.index("Ищу Full Stack") < text.index("Что важно:")
    assert text.index("Что важно:") < text.index("Для отклика присылайте")


def test_author_thread_text_excludes_other_peoples_replies():
    """Foreign replies carry other candidates' CVs and trolling — they must never
    reach the vacancy text or the cover letter."""
    blocks = [("@lnkrnchk", ROOT), ("@so_silly_seal", FOREIGN)]
    text = author_thread_text(blocks, "@lnkrnchk")
    assert "Навайбкодили" not in text


def test_author_thread_text_matches_the_handle_case_insensitively_and_without_at():
    blocks = [("LnkRnchk", ROOT)]
    assert "Ищу Full Stack" in author_thread_text(blocks, "@lnkrnchk")


def test_the_contact_line_survives_chrome_stripping_verbatim():
    """This module's job ends at handing the contact line through intact. Whether
    `detect_contact` can then read "@ skyluckwalker" depends on the shape the DOM
    reader emits, which is Task 6's problem — see the note below."""
    blocks = [("@lnkrnchk", ROOT), ("@lnkrnchk", REPLY_2)]
    text = author_thread_text(blocks, "@lnkrnchk")
    assert "Для отклика присылайте портфолио в Telegram: @ skyluckwalker" in text


def test_author_thread_text_is_empty_when_the_author_posted_nothing():
    assert author_thread_text([("@someone_else", FOREIGN)], "@lnkrnchk") == ""
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

Run: `sender/.venv/bin/python -m pytest sender/tests/test_threads_post.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.domain.threads_post'`

- [ ] **Step 3: Реализовать**

Создать `sender/app/domain/threads_post.py`:

```python
"""Assembling a Threads thread's vacancy text out of what the DOM hands us.

Pure by design: the DOM reading lives in infrastructure/threads_thread.py, so the
part that decides what IS the vacancy stays testable on recorded span texts.

A Threads vacancy is a thread, not a post: the root post carries the opening, and
the author continues in self-replies — that is where the second half of the
requirements and, crucially, the contact to apply to live. Other people's replies
in the same thread are trolling and other candidates' CVs, and must never be mixed
into the vacancy text.
"""
import re

# Engagement counters under a post: likes / replies / reposts. Always numeric, and
# Threads groups thousands with a thin space ("3 438").
_COUNTER_RE = re.compile(r"^[\d\s  .,]+$")
# A relative timestamp: "1 дн.", "2h", "15 мин", "3 d".
_TIME_RE = re.compile(r"^\d+\s*[^\W\d_]{1,5}\.?$", re.UNICODE)
_SEPARATORS = {"·", "•", "|", "—", "-"}
# Sentence-ish punctuation: a chrome token never has it, a real line usually does.
_SENTENCE_CHARS = set(".!?:;,")
# A body line often opens with a list marker instead of a word.
_LIST_MARKERS = ("—", "–", "-", "•", "*", "→")
# Longest a chrome token can plausibly be ("hiring", "Автор", "Author", "1 дн.").
_CHROME_MAX_CHARS = 12


def _is_chrome(part: str) -> bool:
    """True when `part` is interface furniture, not post text.

    Deliberately shape-based, not word-based: the author badge is localised
    («Автор» / "Author") and the profile tag is whatever the user typed, so
    matching on their text would break on the next account or UI language.
    """
    p = part.strip()
    if not p or p in _SEPARATORS:
        return True
    if _COUNTER_RE.match(p) or _TIME_RE.match(p):
        return True
    # A short single word with no sentence punctuation: the "hiring" profile tag,
    # the «Автор»/"Author" badge. A real body line is longer, punctuated, or opens
    # with a list marker.
    return (len(p) <= _CHROME_MAX_CHARS
            and " " not in p
            and not (set(p) & _SENTENCE_CHARS)
            and not p.startswith(_LIST_MARKERS))


def post_body(parts: list[str]) -> str:
    """Text of one post from its span texts, without the interface chrome.

    Leading chrome (profile tag, timestamp, separator, author badge) is dropped
    until the first real line; trailing chrome (engagement counters) is dropped
    from the end. Anything in between is kept verbatim — a bare number in the
    middle of a post is part of the text (a budget, a headcount), not a counter.
    """
    cleaned = [p.strip() for p in parts if p and p.strip()]
    start = 0
    while start < len(cleaned) and _is_chrome(cleaned[start]):
        start += 1
    end = len(cleaned)
    while end > start and _is_chrome(cleaned[end - 1]):
        end -= 1
    return "\n".join(cleaned[start:end])


def _same_handle(a: str, b: str) -> bool:
    return a.strip().lstrip("@").lower() == b.strip().lstrip("@").lower()


def author_thread_text(blocks: list[tuple[str, list[str]]], author: str) -> str:
    """Vacancy text = the author's own posts, in thread order, joined.

    `blocks` is [(handle, span_texts)] in document order, as read off the page.
    Matching is on the handle, NOT on the localised «Автор» badge.
    """
    bodies = []
    for handle, parts in blocks:
        if not _same_handle(handle, author):
            continue
        body = post_body(parts)
        if body:
            bodies.append(body)
    return "\n\n".join(bodies)
```

- [ ] **Step 4: Запустить тесты и убедиться, что всё проходит**

Run: `sender/.venv/bin/python -m pytest sender/tests/test_threads_post.py -v`
Expected: PASS (14 тестов)

- [ ] **Step 5: Коммит**

```bash
git add sender/app/domain/threads_post.py sender/tests/test_threads_post.py
git commit -m "feat(send): чистая сборка текста вакансии из треда Threads"
```

---

### Task 6: Sender — DOM-ридер и анонимный рендер треда

**Files:**
- Create: `sender/app/infrastructure/threads_thread.py`
- Test: `sender/tests/test_threads_thread.py`

**Interfaces:**
- Consumes: `author_thread_text` из Task 5, `threads_author`-подобный разбор URL (реализуется здесь как `author_from_url`).
- Produces:
  - `author_from_url(url: str) -> str` → `"@handle"` или `""`.
  - `read_thread_blocks(page) -> list[tuple[str, list[str]]]` — тонкий DOM-ридер (один `page.evaluate`).
  - `resolve_thread(page, url: str) -> str` — открывает URL, возвращает текст автора («» при любой неудаче).
  - `render_thread(url: str, headless: bool = True) -> str` — поднимает **анонимный** браузер и возвращает то же.

> **Правка от 2026-07-26 (по итогам ревью Task 4): в этой задаче надо решить, как
> склеивать упоминание.** Отрендеренный DOM отдаёт контактную строку как
> `«… в Telegram: @ skyluckwalker»` — с пробелом после собачки. Первоначально план
> лечил это в `detect_contact`, добавив `@\s?` в `_HANDLE_RE`. Это оказалось неверным:
> правило второе из шести, поэтому оно **перехватывает** email, linkedin и hh, и
> `«пишите hr @ acme.com или в телеграм @ivan_hr»` давало `@acme` вместо `@ivan_hr`, а
> `«разработчик @ Astana, откликайтесь на hh.ru/vacancy/12345»` давало `@Astana` вместо
> hh-вакансии. `@ Company` — обычная конвенция в вакансиях, так что это не экзотика.
> `\s?` откачен, `detect_contact` снова точная копия интейкового.
>
> Значит пробел — артефакт рендеринга, и лечить его надо **здесь**. Перед реализацией
> выяснить живьём, откуда он берётся, и выбрать по результату:
>
> 1. **Упоминание — это якорь.** Threads линкует упоминания как `a[href^="/@"]`. Если
>    `skyluckwalker` лежит внутри такого якоря, склеивай только текст якорей — тогда
>    прозаическое `@ Astana` не затрагивается вообще, и это самый точный вариант.
> 2. **Пробел приходит от `innerText` на границе инлайн-элементов.** Тогда у того же
>    узла `textContent` вернёт склеенное. Глобально подменять нельзя — `innerText`
>    держит переводы строк, которые разделяют пункты списка. Читать `textContent`
>    только там, где узел не содержит переводов строк.
> 3. **Ни то, ни другое** — сообщи, не угадывай. Нормализация `@\s+` → `@` по всему
>    тексту вернёт ровно ту проблему, из-за которой откатили `\s?`, поэтому это
>    последний вариант и только с явным решением человека.
>
> Проверить надо на живом посте: `https://www.threads.com/@lnkrnchk/post/DbL4LxBl6v9`,
> строка «Для отклика присылайте портфолио в Telegram: @ skyluckwalker». Тест на то,
> что `detect_contact` находит в собранном тексте `@skyluckwalker`, переехал сюда из
> Task 5 — добавить его после того, как форма известна.

- [ ] **Step 1: Написать падающие тесты**

Создать `sender/tests/test_threads_thread.py`:

```python
"""The DOM reader is thin, so these tests fake the page object — the same pattern
used by test_linkedin_channel.py and test_headhunter_channel.py."""
import pytest

from app.infrastructure.threads_thread import (
    author_from_url, read_thread_blocks, resolve_thread,
)

_URL = "https://www.threads.com/@lnkrnchk/post/DbL4LxBl6v9"

_BLOCKS = [
    ["@lnkrnchk", ["hiring", "1 дн.", "Ищу Full Stack Developer.", "32"]],
    ["@lnkrnchk", ["hiring", "1 дн.", "·", "Автор", "Что важно: опыт с Lovable.", "1"]],
    ["@lnkrnchk", ["hiring", "1 дн.", "·", "Автор",
                   "Для отклика присылайте портфолио в Telegram: @ skyluckwalker", "1"]],
    ["@troll", ["1 дн.", "Навайбкодили нейрослоп.", "3"]],
]


class FakePage:
    """Mimics the bits of a Playwright page that the reader touches."""

    def __init__(self, blocks=None, goto_error=None, eval_error=None):
        self._blocks = blocks if blocks is not None else _BLOCKS
        self._goto_error = goto_error
        self._eval_error = eval_error
        self.goto_calls = []

    def goto(self, url, **kwargs):
        self.goto_calls.append(url)
        if self._goto_error:
            raise self._goto_error

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, script):
        if self._eval_error:
            raise self._eval_error
        return self._blocks


def test_author_from_url():
    assert author_from_url(_URL) == "@lnkrnchk"
    assert author_from_url("https://www.threads.net/@a.b/post/X1") == "@a.b"
    assert author_from_url("https://hh.ru/vacancy/1") == ""
    assert author_from_url("") == ""


def test_read_thread_blocks_normalises_to_tuples():
    blocks = read_thread_blocks(FakePage())
    assert blocks[0] == ("@lnkrnchk", ["hiring", "1 дн.", "Ищу Full Stack Developer.", "32"])
    assert len(blocks) == 4


def test_read_thread_blocks_tolerates_junk_rows():
    page = FakePage(blocks=[["@a", ["text long enough"]], None, ["@b"], "nonsense",
                            ["@c", "not-a-list"]])
    assert read_thread_blocks(page) == [("@a", ["text long enough"])]


def test_resolve_thread_returns_only_the_authors_posts():
    text = resolve_thread(FakePage(), _URL)
    assert "Ищу Full Stack Developer." in text
    assert "Что важно: опыт с Lovable." in text
    assert "@ skyluckwalker" in text
    assert "Навайбкодили" not in text


def test_resolve_thread_keeps_thread_order():
    text = resolve_thread(FakePage(), _URL)
    assert text.index("Ищу Full Stack") < text.index("Что важно") < text.index("Для отклика")


def test_resolve_thread_navigates_to_the_url():
    page = FakePage()
    resolve_thread(page, _URL)
    assert page.goto_calls == [_URL]


def test_resolve_thread_returns_empty_when_navigation_fails():
    """A login wall, a timeout or a network blip must not raise: the caller falls
    back to the 480 chars the intake already stored."""
    assert resolve_thread(FakePage(goto_error=RuntimeError("timeout")), _URL) == ""


def test_resolve_thread_returns_empty_when_the_dom_read_fails():
    assert resolve_thread(FakePage(eval_error=RuntimeError("detached")), _URL) == ""


def test_resolve_thread_returns_empty_when_the_page_has_no_posts():
    assert resolve_thread(FakePage(blocks=[]), _URL) == ""


def test_resolve_thread_returns_empty_for_a_non_threads_url():
    assert resolve_thread(FakePage(), "https://hh.ru/vacancy/1") == ""
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

Run: `sender/.venv/bin/python -m pytest sender/tests/test_threads_thread.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.infrastructure.threads_thread'`

- [ ] **Step 3: Реализовать**

Создать `sender/app/infrastructure/threads_thread.py`. JS проверен живьём 2026-07-26 на реальном треде — не менять селекторы без повторной проверки:

```python
"""Reading a whole Threads thread in a browser.

Why a browser at all: `og:description` (what the intake bot reads over plain HTTP)
carries the ROOT post only. The second half of the requirements and the contact to
apply to live in the author's self-replies, which are absent from the anonymous
HTML entirely — verified 2026-07-26, zero occurrences of the contact handle in
545 KB of server-rendered markup.

This renders ANONYMOUSLY: no storage_state, no session. Reading a public post is
not an action that needs an account, so the resolve path carries none of the ban
risk that posting from a logged-in Threads account does. Only ThreadsChannel (the
DM fallback) touches the saved session.

DOM interaction is isolated here on purpose, the same way channels/linkedin.py
isolates its selectors: they drift. The decision of what IS the vacancy is pure
and lives in domain/threads_post.py.
"""
import re

from app.domain.threads_post import author_thread_text

_AUTHOR_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?threads\.(?:com|net)/@([\w.]+)/post/[\w-]+",
    re.IGNORECASE)

# Wait for the thread to hydrate. The posts are client-rendered, so a goto() that
# resolves is not a page that has content yet.
_SETTLE_MS = 2500
_GOTO_TIMEOUT_MS = 30000

# Verified live 2026-07-26. Anchored on semantics, not on Meta's generated class
# names (`x1a6qonq x6ikm8r …`), which change without notice:
#
#  * every post carries an author link `a[href^="/@"]` -> that is the handle, and it
#    is locale-independent (unlike the «Автор»/"Author" badge);
#  * a post block = the nearest ancestor of that link holding real text;
#  * the whole-thread wrapper matches too (it starts with «Ветка … просмотров»), so
#    any block that CONTAINS another block is dropped;
#  * the body sits in `span[dir="auto"]`, split one span per paragraph. Taking only
#    the longest span drops the opening paragraphs, so every leaf span is collected
#    in DOM order; spans inside the author link are skipped (they are the handle).
_READ_BLOCKS_JS = """
() => {
  const blocks = [], seen = new Set();
  for (const a of document.querySelectorAll('a[href^="/@"]')) {
    let el = a, hops = 0, b = null;
    while (el && hops < 6) {
      if ((el.innerText || '').trim().length > 40) { b = el; break; }
      el = el.parentElement; hops++;
    }
    if (b && !seen.has(b)) {
      seen.add(b);
      blocks.push({ el: b, handle: a.getAttribute('href').split('/')[1] });
    }
  }
  const kept = blocks.filter(x => !blocks.some(y => y !== x && x.el.contains(y.el)));
  return kept.map(({ el, handle }) => {
    const spans = [...el.querySelectorAll('span[dir="auto"]')].filter(s =>
      !s.querySelector('span[dir="auto"]') && !s.closest('a[href^="/@"]'));
    const parts = [];
    for (const s of spans) {
      const t = (s.innerText || '').trim();
      if (t && !parts.includes(t)) parts.push(t);
    }
    return [handle, parts];
  });
}
"""


def author_from_url(url: str) -> str:
    """'@handle' of the post author from the post URL, or '' if not a post URL."""
    m = _AUTHOR_RE.match((url or "").strip())
    return "@" + m.group(1) if m else ""


def read_thread_blocks(page) -> list[tuple[str, list[str]]]:
    """[(handle, span_texts)] for every post on the page, in document order."""
    raw = page.evaluate(_READ_BLOCKS_JS) or []
    blocks = []
    for row in raw:
        # The page is not ours; never trust its shape.
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            continue
        handle, parts = row
        if not isinstance(handle, str) or not isinstance(parts, list):
            continue
        blocks.append((handle, [p for p in parts if isinstance(p, str)]))
    return blocks


def resolve_thread(page, url: str) -> str:
    """The author's own posts in `url`, joined, or "" if the thread can't be read.

    Never raises: a login wall, a timeout, a detached frame or a layout change all
    mean the caller keeps whatever text the intake already stored.
    """
    author = author_from_url(url)
    if not author:
        return ""
    try:
        page.goto(url, timeout=_GOTO_TIMEOUT_MS, wait_until="domcontentloaded")
        page.wait_for_timeout(_SETTLE_MS)
        blocks = read_thread_blocks(page)
    except Exception:  # noqa: BLE001 — an unreadable thread is not a lost lead
        return ""
    return author_thread_text(blocks, author)


def render_thread(url: str, headless: bool = True) -> str:
    """Open an anonymous browser, read the thread, close it. "" on any failure."""
    from playwright.sync_api import sync_playwright

    pw = browser = None
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=headless)
        # No storage_state: this is a public read, it must not touch the session.
        page = browser.new_context().new_page()
        return resolve_thread(page, url)
    except Exception:  # noqa: BLE001
        return ""
    finally:
        if browser:
            try:
                browser.close()
            except Exception:  # noqa: BLE001
                pass
        if pw:
            try:
                pw.stop()
            except Exception:  # noqa: BLE001
                pass
```

- [ ] **Step 4: Запустить тесты и убедиться, что всё проходит**

Run: `sender/.venv/bin/python -m pytest sender/tests/test_threads_thread.py -v`
Expected: PASS (10 тестов)

- [ ] **Step 5: Коммит**

```bash
git add sender/app/infrastructure/threads_thread.py sender/tests/test_threads_thread.py
git commit -m "feat(send): анонимный рендер треда Threads и DOM-ридер постов автора"
```

---

### Task 7: Sender — атомарная перезапись лида в таблице

**Files:**
- Modify: `sender/app/domain/lead.py:18-22`
- Modify: `sender/app/infrastructure/sheets_repo.py` (добавить метод в `SheetsRepo`)
- Test: `sender/tests/test_sheets_writes.py`

**Interfaces:**
- Produces: константы `COL_PLATFORM`, `COL_TARGET`, `COL_VACANCY` в `app.domain.lead`; метод `SheetsRepo.update_resolved(lead, platform: str, target: str, vacancy_context: str, note: str = "") -> None`.

- [ ] **Step 1: Написать падающий тест**

Добавить в `sender/tests/test_sheets_writes.py` (следовать стилю уже существующих там тестов — если модуль использует фейковый worksheet, переиспользовать его):

```python
# --- resolved threads leads ------------------------------------------------

from app.domain.lead import COL_NOTE, COL_PLATFORM, COL_TARGET, COL_VACANCY  # noqa: E402


def test_lead_column_indexes_match_the_header():
    from app.domain.lead import COLUMNS
    assert COLUMNS[COL_PLATFORM - 1] == "Платформа"
    assert COLUMNS[COL_TARGET - 1] == "Источник"
    assert COLUMNS[COL_VACANCY - 1] == "Вакансия"


def test_platform_target_and_vacancy_are_adjacent():
    """update_resolved writes them as ONE span; if a column is ever inserted
    between them that span would silently overwrite the wrong cell."""
    assert COL_TARGET == COL_PLATFORM + 1
    assert COL_VACANCY == COL_TARGET + 1


def test_update_resolved_writes_the_row_in_one_batch(fake_ws_repo):
    """A threads lead becomes a telegram lead: platform, target and vacancy text
    must land together or not at all — a half-applied rewrite would leave the lead
    pointing at a Threads URL with a Telegram platform."""
    repo, ws = fake_ws_repo
    lead = _lead(row=5)

    repo.update_resolved(lead, "telegram", "@skyluckwalker",
                         "Ищу Full Stack Developer", note="резолв из Threads")

    assert len(ws.batch_updates) == 1, "должна быть одна операция записи"
    ranges = {u["range"] for u in ws.batch_updates[0]}
    assert any(":" in r for r in ranges), "платформа/источник/вакансия пишутся спаном"
    values = [u["values"] for u in ws.batch_updates[0]]
    assert [["telegram", "@skyluckwalker", "Ищу Full Stack Developer"]] in values
    assert [["резолв из Threads"]] in values


def test_update_resolved_without_a_note_writes_only_the_span(fake_ws_repo):
    repo, ws = fake_ws_repo
    repo.update_resolved(_lead(row=5), "telegram", "@x", "текст")
    assert len(ws.batch_updates[0]) == 1


def test_update_resolved_never_touches_status(fake_ws_repo):
    """The lead stays `new` — it has not been sent yet."""
    repo, ws = fake_ws_repo
    repo.update_resolved(_lead(row=5), "telegram", "@x", "текст", note="n")
    from app.domain.lead import COL_STATUS
    from gspread.utils import rowcol_to_a1
    status_cell = rowcol_to_a1(5, COL_STATUS)
    for u in ws.batch_updates[0]:
        assert status_cell not in u["range"]
```

Если в файле ещё нет фикстуры `fake_ws_repo` и хелпера `_lead`, добавить их:

```python
import pytest

from app.domain.lead import Lead, STATUS_NEW
from app.infrastructure.sheets_repo import SheetsRepo


def _lead(row=2, platform="threads",
          target="https://www.threads.com/@lnkrnchk/post/DbL4LxBl6v9"):
    return Lead(row=row, lead_id="7", platform=platform, target=target,
                vacancy_context="короткий текст", raw_text=target, status=STATUS_NEW)


class _FakeWorksheet:
    def __init__(self):
        self.batch_updates = []
        self.updates = []

    def batch_update(self, data, **kwargs):
        self.batch_updates.append(data)

    def update(self, values, cells, **kwargs):
        self.updates.append((values, cells))


@pytest.fixture
def fake_ws_repo():
    repo = SheetsRepo.__new__(SheetsRepo)      # skip gspread auth
    ws = _FakeWorksheet()
    repo._ws = ws
    return repo, ws
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

Run: `sender/.venv/bin/python -m pytest sender/tests/test_sheets_writes.py -v -k resolved`
Expected: FAIL — `ImportError: cannot import name 'COL_PLATFORM'`

- [ ] **Step 3: Реализовать константы**

В `sender/app/domain/lead.py` после `COL_MESSAGE` добавить:

```python
COL_PLATFORM = COLUMNS.index("Платформа") + 1
COL_TARGET = COLUMNS.index("Источник") + 1
COL_VACANCY = COLUMNS.index("Вакансия") + 1
```

И обновить комментарий поля `platform` в `Lead`:

```python
    platform: str          # telegram | linkedin | hh | email | wellfound | threads
```

- [ ] **Step 4: Реализовать метод**

Добавить в класс `SheetsRepo` (после `mark_status`):

```python
    def update_resolved(self, lead: Lead, platform: str, target: str,
                        vacancy_context: str, note: str = "") -> None:
        """Rewrite where a lead goes and what it says, in one API call.

        A Threads lead arrives pointing at a post URL with only the root post's
        text. Once the thread is read, the real contact is usually somewhere else
        entirely ("Для отклика присылайте портфолио в Telegram: @…"), so platform,
        target and vacancy text all change together. They are adjacent columns, so
        they go as one span; the note is a separate range because Сообщение/Статус/
        Дата отправки sit between them and writing one wide span would blank those.

        Status is deliberately untouched: the lead has not been sent yet, it stays
        `new`. A half-applied rewrite would be the worst outcome — a lead labelled
        telegram whose target is still a Threads URL — hence one atomic write.
        """
        updates = [{
            "range": (f"{rowcol_to_a1(lead.row, COL_PLATFORM)}"
                      f":{rowcol_to_a1(lead.row, COL_VACANCY)}"),
            "values": [[platform, target, vacancy_context]],
        }]
        if note:
            updates.append({
                "range": rowcol_to_a1(lead.row, COL_NOTE),
                "values": [[note]],
            })
        _with_retry(lambda: self._ws.batch_update(
            updates, value_input_option=ValueInputOption.raw))
```

Добавить `COL_PLATFORM`, `COL_TARGET`, `COL_VACANCY` в импорт из `app.domain.lead` в начале `sheets_repo.py`.

> `value_input_option=raw`: текст вакансии соскрейплен, ведущий `=` должен остаться текстом, а не стать формулой — та же причина, что в `mark_sent`.

- [ ] **Step 5: Запустить тесты и убедиться, что всё проходит**

Run: `sender/.venv/bin/python -m pytest sender/tests/test_sheets_writes.py sender/tests/test_sheets_mapping.py -v`
Expected: PASS

- [ ] **Step 6: Коммит**

```bash
git add sender/app/domain/lead.py sender/app/infrastructure/sheets_repo.py \
        sender/tests/test_sheets_writes.py
git commit -m "feat(send): атомарная перезапись платформы, источника и текста лида"
```

---

### Task 8: Sender — юзкейс резолва и встраивание в цикл отправки

> **Правка от 2026-07-26 (решение человека): модель как запасной детектор контакта.**
> Живая проверка в Task 6 показала, что пробел в `«Telegram: @ skyluckwalker»` поставил
> сам автор поста, а не рендеринг: `innerText === textContent`, якоря нет, в payload'е
> Threads `linkified_in_app_url: null`. Правилами такое не берётся, а людей, пишущих
> контакт как попало («телега: nick», «почта name собака domain»), не покрыть регексом
> в принципе.
>
> Решение человека: склеивать, и пусть тип контакта определяет модель.
>
> **Это перекрывает записанный принцип проекта.** В `contact.py` стоит: «Platform
> detection is rule-based on purpose: it decides where the message is later sent, so it
> must not depend on an LLM guess». Принцип не отменяется, а сужается, и вот чем он
> заменён:
>
> 1. **Правила решают первыми.** Модель вызывается **только** когда `detect_contact`
>    вернул `None`. Все существующие лиды идут прежним детерминированным путём.
> 2. **Только для Threads.** Вызов живёт в резолвере; интейк, hh, LinkedIn и wellfound
>    не затрагиваются.
> 3. **Ответ модели проверяется, а не принимается.** Платформа обязана быть из
>    известного набора, target обязан пройти проверку формы для этой платформы, и —
>    главное — **ядро target'а обязано встречаться в исходном тексте треда**. Это
>    защита от выдумывания: модель физически не может вернуть ник, которого в треде
>    не было.
> 4. **Хендл автора отбрасывается** и здесь тоже (см. правку выше).
> 5. **Видно человеку.** В заметку лида пишется, что контакт определён моделью, и это
>    же печатается на подтверждении в `make run`, где есть клавиша правки.
>
> Модель — `OPENAI_MODEL` (не дешёвая): вызов один на лид, лидов единицы в неделю, а
> цена ошибки — сообщение не тому человеку.

**Files:**
- Create: `sender/app/application/contact_llm.py` — **чистые** сборка промпта, разбор и
  валидация ответа. Ни сети, ни клиента; по образцу `application/relevance.py`.
- Create: `sender/app/infrastructure/openai_contact.py` — тонкая обёртка над OpenAI, по
  образцу `infrastructure/openai_relevance.py`.
- Create: `sender/app/application/resolve_threads_lead.py`
- Modify: `sender/app/interface/cli.py:32` (`_KNOWN`) и цикл отправки
- Test: `sender/tests/test_contact_llm.py`, `sender/tests/test_resolve_threads_lead.py`

**Interfaces:**
- Consumes: `resolve_thread`/`render_thread` (Task 6), `detect_contact` (Task 4), `SheetsRepo.update_resolved` (Task 7).
- Produces:
  - `build_contact_prompt(thread_text: str) -> tuple[str, str]` — (system, user).
  - `parse_contact_response(raw: str, source_text: str, author: str) -> Contact | None` —
    разбирает, валидирует и **отбрасывает всё сомнительное**. Возвращает `None` при
    любой из проверок ниже.
  - `resolve_threads_lead(lead, repo, render, detect=detect_contact, llm=None) -> Lead` —
    `llm` вызываемое `(thread_text) -> str` (сырой ответ модели) или `None`, тогда
    запасной детектор просто не используется и поведение прежнее.

**Проверки в `parse_contact_response` (все обязательны, каждая со своим тестом):**

| Проверка | Почему |
|---|---|
| Ответ разбирается как JSON, иначе `None` | модель может ответить прозой |
| `platform` ∈ `{telegram, email, linkedin, hh, wellfound}` | платформа вне набора сломает `build_channel` |
| `target` проходит проверку формы своей платформы (телеграм-ник `[A-Za-z0-9_]{5,32}`, email по регексу, остальные — URL нужного хоста) | модель вернёт «пиши в тг» вместо ника |
| **Ядро `target` встречается в `source_text`** (без учёта регистра, `@` и пробелов) | **защита от выдумывания** — ник, которого не было в треде, отбрасывается |
| `platform == telegram` и `target` равен автору поста → `None` | ник автора в Threads не является телеграм-ником |

Промпт обязан требовать строгий JSON и явно запрещать додумывать: если контакта в
тексте нет, модель возвращает `{"platform": null}`.

- [ ] **Step 1: Написать падающие тесты**

Создать `sender/tests/test_resolve_threads_lead.py`:

```python
"""Resolving a threads lead into a sendable one.

Two invariants are load-bearing here and are asserted directly: a lead is never
lost, and it is never auto-skipped. The worst acceptable outcome is "stays as it
was, with a note".
"""
from app.application.resolve_threads_lead import resolve_threads_lead
from app.domain.lead import STATUS_NEW, Lead

_URL = "https://www.threads.com/@lnkrnchk/post/DbL4LxBl6v9"

_FULL = ("Ищу Full Stack Developer (Lovable / Claude Code / AI-first).\n\n"
         "Что важно: опыт с Lovable, Claude Code, Cursor, Supabase.\n\n"
         "Для отклика присылайте портфолио в Telegram: @ skyluckwalker")


def _lead(**kw):
    base = dict(row=5, lead_id="7", platform="threads", target=_URL,
                vacancy_context="Ищу Full Stack Developer (обрезано)",
                raw_text=_URL, status=STATUS_NEW)
    base.update(kw)
    return Lead(**base)


class FakeRepo:
    def __init__(self):
        self.resolved = []
        self.statuses = []

    def update_resolved(self, lead, platform, target, vacancy_context, note=""):
        self.resolved.append((lead.row, platform, target, vacancy_context, note))

    def mark_status(self, lead, status, note=""):
        self.statuses.append((lead.row, status, note))


def test_contact_found_in_the_thread_switches_the_platform():
    repo = FakeRepo()
    out = resolve_threads_lead(_lead(), repo, render=lambda url: _FULL)
    assert out.platform == "telegram"
    assert out.target == "@skyluckwalker"
    assert "Что важно" in out.vacancy_context


def test_contact_found_is_persisted_once():
    repo = FakeRepo()
    resolve_threads_lead(_lead(), repo, render=lambda url: _FULL)
    assert len(repo.resolved) == 1
    row, platform, target, text, note = repo.resolved[0]
    assert (row, platform, target) == (5, "telegram", "@skyluckwalker")
    assert "Что важно" in text
    assert _URL in note, "в заметке должна остаться ссылка на исходный тред"


def test_no_contact_in_the_thread_keeps_threads_and_targets_the_author():
    """The DM fallback: platform stays threads, target becomes the author."""
    repo = FakeRepo()
    text = "Ищем разработчика. Формат: удалённо, full-time. Пишите в комментарии."
    out = resolve_threads_lead(_lead(), repo, render=lambda url: text)
    assert out.platform == "threads"
    assert out.target == "@lnkrnchk"
    assert out.vacancy_context == text
    assert repo.resolved[0][1] == "threads"


def test_render_failure_leaves_the_lead_untouched():
    """No render, no rewrite: the 480 chars from intake are still better than
    nothing, and the lead must stay `new` for the next run."""
    repo = FakeRepo()
    original = _lead()
    out = resolve_threads_lead(original, repo, render=lambda url: "")
    assert out is original
    assert repo.resolved == []


def test_render_failure_is_never_a_skip():
    repo = FakeRepo()
    resolve_threads_lead(_lead(), repo, render=lambda url: "")
    assert repo.statuses == [], "резолв не имеет права ставить терминальный статус"


def test_render_raising_is_swallowed():
    repo = FakeRepo()

    def boom(url):
        raise RuntimeError("browser died")

    out = resolve_threads_lead(_lead(), repo, render=boom)
    assert out.platform == "threads" and repo.resolved == []


def test_a_persist_failure_still_returns_the_resolved_lead_in_memory():
    """Sheets being down must not cost us the send: the rewrite is a convenience,
    the in-memory lead is what the run uses."""
    class BrokenRepo(FakeRepo):
        def update_resolved(self, *a, **kw):
            raise RuntimeError("sheets 503")

    out = resolve_threads_lead(_lead(), BrokenRepo(), render=lambda url: _FULL)
    assert out.platform == "telegram" and out.target == "@skyluckwalker"


def test_the_authors_own_handle_is_not_treated_as_a_telegram_contact():
    """Found while implementing Task 4. "@lnkrnchk" written by @lnkrnchk in their
    own post is their THREADS name, not a Telegram username — DMing it would reach
    a different person. The intake copy of detect_contact exempts the author from
    the URL; the sender copy gets rendered prose with no URL, so the guard is here."""
    repo = FakeRepo()
    text = "Ищем разработчика. Пишите мне @lnkrnchk, отвечаю быстро."
    out = resolve_threads_lead(_lead(), repo, render=lambda url: text)
    assert out.platform == "threads"
    assert out.target == "@lnkrnchk"          # the DM fallback, not a Telegram DM


def test_a_different_handle_in_the_authors_post_still_wins():
    repo = FakeRepo()
    text = "Ищем разработчика. Резюме в Telegram: @hiring_bot_hr"
    out = resolve_threads_lead(_lead(), repo, render=lambda url: text)
    assert out.platform == "telegram"
    assert out.target == "@hiring_bot_hr"


def test_non_threads_leads_are_returned_as_is():
    repo = FakeRepo()
    lead = _lead(platform="hh", target="https://hh.ru/vacancy/1")
    called = []
    out = resolve_threads_lead(lead, repo, render=lambda url: called.append(url) or "")
    assert out is lead and called == []


def test_shorter_resolved_text_does_not_replace_a_longer_stored_one():
    """A partial render (hydration lost a reply) must not shrink the vacancy."""
    repo = FakeRepo()
    lead = _lead(vacancy_context="a" * 900)
    out = resolve_threads_lead(lead, repo, render=lambda url: "короткий огрызок")
    assert out.vacancy_context == "a" * 900
```

- [ ] **Step 2: Запустить тесты и убедиться, что они падают**

Run: `sender/.venv/bin/python -m pytest sender/tests/test_resolve_threads_lead.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.application.resolve_threads_lead'`

- [ ] **Step 3: Реализовать юзкейс**

Создать `sender/app/application/resolve_threads_lead.py`:

```python
"""Turning a Threads lead into a sendable one.

The intake bot can only read a Threads post's ROOT text over plain HTTP, and it
cannot see the contact at all — that lives in the author's self-replies. So a
threads lead arrives deliberately incomplete, and this closes the gap right before
the message is generated: read the whole thread, find the real contact, and point
the lead at it.

Two invariants:
  * the lead is never lost — every failure path returns a usable lead;
  * the lead is never auto-skipped — no terminal status is written here at all.
"""
from dataclasses import replace

from app.domain.contact import detect_contact
from app.infrastructure.threads_thread import author_from_url


def resolve_threads_lead(lead, repo, render, detect=detect_contact):
    """A threads `lead` re-pointed at the real contact found inside its thread.

    `render(url) -> str` returns the author's own posts joined, or "" if the thread
    could not be read. Returns the lead to send: rewritten when the thread was
    read, the original object otherwise.
    """
    if lead.platform != "threads":
        return lead

    try:
        text = render(lead.target)
    except Exception:  # noqa: BLE001 — an unreadable thread is not a lost lead
        text = ""
    if not text:
        # Keep whatever the intake stored. Status stays `new` so the next run,
        # possibly with a working browser, tries again.
        return lead

    # A partial render (hydration dropped a reply) must never shrink the vacancy.
    vacancy = text if len(text) >= len(lead.vacancy_context or "") else lead.vacancy_context

    author = author_from_url(lead.target)
    contact = detect(text)
    # The author's own Threads handle is NOT a Telegram username. When they write
    # "пишите мне @lnkrnchk" in their own post, detect_contact reads it as Telegram
    # and we would DM whoever holds that name there — a different person. The
    # intake copy of detect_contact guards this by exempting the author parsed out
    # of the URL; the sender copy cannot, because its input is rendered prose with
    # no URL in it. So the guard lives here, where the author IS known.
    if contact is not None and contact.platform == "telegram" and author:
        if contact.target.strip().lstrip("@").lower() == author.lstrip("@").lower():
            contact = None

    if contact is not None:
        platform, target = contact.platform, contact.target
        note = f"контакт из треда Threads: {lead.target}"
    else:
        # Nothing to apply to but the author — the DM fallback.
        platform = "threads"
        target = author or lead.target
        note = f"контакта в треде нет, DM автору: {lead.target}"

    try:
        repo.update_resolved(lead, platform, target, vacancy, note=note)
    except Exception:  # noqa: BLE001 — the sheet is a record, the send is the point
        pass

    return replace(lead, platform=platform, target=target, vacancy_context=vacancy)
```

- [ ] **Step 4: Запустить тесты и убедиться, что всё проходит**

Run: `sender/.venv/bin/python -m pytest sender/tests/test_resolve_threads_lead.py -v`
Expected: PASS (10 тестов)

- [ ] **Step 5: Встроить в цикл отправки**

> **Порядок обязателен: резолв идёт ДО `switcher.for_platform(platform)`.** Резолв
> меняет `lead.platform`, поэтому если открыть канал раньше, для threads-лида
> поднимется Threads-браузер вместо Telegram — и лид уйдёт в DM вместо личного
> сообщения, ради которого весь резолв и делался. Блок ниже вставляется **выше**
> строки `channel = switcher.for_platform(platform)`; `sender = SendOutreach(channel)`
> остаётся там, где был.

5a. В `sender/app/interface/cli.py:32` добавить `threads` в `_KNOWN`:

```python
# Platforms the send loop can build a channel for. A platform missing here is a
# per-lead skip in skip_reason(), so forgetting to add one silently buries its leads.
_KNOWN = {"telegram", "linkedin", "hh", "email", "wellfound", "threads"}
```

5b. В `run()` вставить блок резолва **между** `reason = skip_reason(...)` / `continue`
и строкой `channel = switcher.for_platform(platform)`. Существующий блок
`print(f"Лид #{lead.lead_id} …")` **не трогать** — он ниже и напечатает уже
обновлённые `platform` и `lead.target` сам:

```python
            if lead.platform == "threads":
                # og:description gave the intake the root post only; the rest of the
                # vacancy and the contact live in the author's self-replies, which
                # need a browser. Anonymous render: reading a public post must not
                # touch the saved session.
                from app.application.resolve_threads_lead import resolve_threads_lead
                from app.infrastructure.threads_thread import render_thread
                print("Читаю тред Threads...")
                lead = resolve_threads_lead(
                    lead, repo,
                    render=lambda u: render_thread(u, headless=config.BROWSER_HEADLESS))
                if lead.platform != platform:
                    print(f"   контакт найден: {lead.platform} → {lead.target}")
                    platform = lead.platform
                else:
                    print(f"   контакта в треде нет, буду писать автору: {lead.target}")
```

- [ ] **Step 6: Прогнать весь набор sender**

Run: `make test-unit`
Expected: PASS — весь набор, включая `test_send_outreach.py` и `test_send_plan.py`.

- [ ] **Step 7: Коммит**

```bash
git add sender/app/application/resolve_threads_lead.py sender/app/interface/cli.py \
        sender/tests/test_resolve_threads_lead.py
git commit -m "feat(send): дочитывать тред Threads и переводить лид на реальный контакт"
```

---

### Task 9: Sender — сессия, канал, регистрация, конфиг

**Files:**
- Create: `sender/app/infrastructure/threads_session.py`
- Create: `sender/app/infrastructure/channels/threads.py`
- Modify: `sender/app/infrastructure/channels/registry.py:49-69`
- Modify: `sender/app/config.py` (блок per-platform settings, `platform_enabled`)
- Modify: `sender/tests/test_channel_contract.py:10-24`
- Test: `sender/tests/test_threads_session.py`, `sender/tests/test_threads_channel.py`

**Interfaces:**
- Produces: `has_valid_session(state_path: str, now: float | None = None) -> bool` в `app.infrastructure.threads_session`; класс `ThreadsChannel(state_path: str, headless: bool = False)` с `name="threads"`, `body_limit=500`, `needs_subject=False`; ветка `threads` в `build_channel`; `config.THREADS_STATE_PATH`.

- [ ] **Step 1: Написать падающие тесты сессии**

Создать `sender/tests/test_threads_session.py`:

```python
"""A state file existing is not the same as a live session — the lesson `li_at`
taught on LinkedIn, applied to Threads before it costs a run."""
import json
import time

from app.infrastructure.threads_session import has_valid_session


def _write(tmp_path, cookies):
    p = tmp_path / "threads_state.json"
    p.write_text(json.dumps({"cookies": cookies}))
    return str(p)


def test_missing_file_is_no_session(tmp_path):
    assert has_valid_session(str(tmp_path / "nope.json")) is False


def test_unparseable_file_is_no_session(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{not json")
    assert has_valid_session(str(p)) is False


def test_no_auth_cookie_is_no_session(tmp_path):
    """A logged-out context still saves csrftoken/mid — those are not a login."""
    path = _write(tmp_path, [{"name": "csrftoken", "value": "abc", "expires": -1},
                             {"name": "mid", "value": "xyz", "expires": -1}])
    assert has_valid_session(path) is False


def test_empty_auth_cookie_is_no_session(tmp_path):
    path = _write(tmp_path, [{"name": "sessionid", "value": "   ", "expires": -1}])
    assert has_valid_session(path) is False


def test_live_auth_cookie_is_a_session(tmp_path):
    path = _write(tmp_path, [{"name": "sessionid", "value": "s%3Aabc",
                              "expires": time.time() + 86400}])
    assert has_valid_session(path) is True


def test_session_cookie_without_expiry_counts(tmp_path):
    for expires in (-1, 0):
        path = _write(tmp_path, [{"name": "sessionid", "value": "s%3Aabc",
                                  "expires": expires}])
        assert has_valid_session(path) is True, expires


def test_expired_auth_cookie_is_no_session(tmp_path):
    path = _write(tmp_path, [{"name": "sessionid", "value": "s%3Aabc",
                              "expires": 1000}])
    assert has_valid_session(path, now=2000) is False
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `sender/.venv/bin/python -m pytest sender/tests/test_threads_session.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.infrastructure.threads_session'`

- [ ] **Step 3: Реализовать проверку сессии**

Создать `sender/app/infrastructure/threads_session.py`:

```python
"""Is a saved Threads Playwright state actually logged in?

Same trap as LinkedIn (see linkedin_session.py): Playwright saves whatever cookies
the context held, so a logged-out context yields a state file full of cookies with
no auth among them. Loading it browses as a guest, and Threads answers with a
login wall — which would surface as a per-lead failure instead of an obvious
"go log in".

Threads runs on Instagram's session, so the auth cookie is Instagram's `sessionid`.
`csrftoken`, `mid` and `ig_did` are present for guests too and are NOT a login
signal. VERIFY THIS NAME on the first real login (`make login_threads`, then look
at the cookies in the state file) — it is the one fact here that was reasoned from
Instagram's scheme rather than observed on a live Threads state.
"""
import json
import time
from pathlib import Path

_AUTH_COOKIE = "sessionid"


def has_valid_session(state_path: str, now: float | None = None) -> bool:
    """True when `state_path` holds a non-empty, unexpired `sessionid` cookie."""
    p = Path(state_path)
    if not p.exists():
        return False
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError):
        return False
    now = time.time() if now is None else now
    for c in data.get("cookies", []):
        if c.get("name") != _AUTH_COOKIE or not (c.get("value") or "").strip():
            continue
        # -1/0 mark a session cookie (no expiry) — still usable from a saved state.
        expires = c.get("expires", -1)
        if expires in (-1, 0) or expires > now:
            return True
    return False
```

- [ ] **Step 4: Написать падающие тесты канала**

Создать `sender/tests/test_threads_channel.py`:

```python
"""ThreadsChannel is the DM fallback: used only when the thread carried no contact."""
import pytest

from app.domain.channel import ChannelUnavailable, OutreachContent
from app.infrastructure.channels.threads import ThreadsChannel, normalize_target


def test_class_attrs_satisfy_the_protocol():
    from app.domain.channel import OutreachChannel
    ch = ThreadsChannel("threads_state.json", True)
    assert isinstance(ch, OutreachChannel)
    assert ch.name == "threads"
    assert ch.needs_subject is False
    assert isinstance(ch.body_limit, int)


def test_normalize_target():
    assert normalize_target("@skyluckwalker") == "skyluckwalker"
    assert normalize_target("skyluckwalker") == "skyluckwalker"
    assert normalize_target("https://www.threads.com/@skyluckwalker") == "skyluckwalker"
    assert normalize_target("  @Sky_1  ") == "Sky_1"


def test_start_without_a_live_session_is_channel_unavailable(tmp_path, monkeypatch):
    """A dead burner session must stop cleanly with a re-login hint, not fail the
    lead: the lead was never attempted."""
    import app.infrastructure.channels.threads as mod
    monkeypatch.setattr(mod, "has_valid_session", lambda p: False)
    with pytest.raises(ChannelUnavailable) as exc:
        ThreadsChannel(str(tmp_path / "s.json"), True).start()
    assert "login_threads" in str(exc.value)


def test_attachment_is_ignored_not_an_error():
    """Threads DMs carry text/photo/video/GIF/sticker only — no documents. A CV
    path must be silently dropped, never crash the send."""
    ch = ThreadsChannel("s.json", True)
    sent = {}
    ch._deliver = lambda handle, body: sent.update(handle=handle, body=body)
    ch.send("@sky", OutreachContent(body="Привет", attachment_path="/cv/me.pdf"))
    assert sent == {"handle": "sky", "body": "Привет"}
```

- [ ] **Step 5: Запустить и убедиться, что падает**

Run: `sender/.venv/bin/python -m pytest sender/tests/test_threads_channel.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.infrastructure.channels.threads'`

- [ ] **Step 6: Реализовать канал**

Создать `sender/app/infrastructure/channels/threads.py`:

```python
"""Threads channel: DMs the post author from a saved (burner) session.

This is the FALLBACK, not the main path. Priority is always the real contact found
inside the thread — a recruiter who posts a vacancy says how to reach them, and
that contact is usually Telegram or email, handled by the existing channels.

Two things to know about a Threads DM:
  * it carries text, photos, video, GIFs and stickers — NO documents, so the CV
    cannot be attached. `attachment_path` is dropped on purpose; the signature
    (added by code, not the model) already carries Telegram and email.
  * a DM to someone who does not follow you lands in their "message requests",
    which recruiters rarely open. Delivery here is genuinely weak, which is why
    this is the last resort.

Threads runs on an Instagram account, so automating it risks that Instagram
account (accepted by the user, on a separate burner account). Selectors drift, so
DOM interaction is confined to _deliver().
"""
import re

from app.domain.channel import ChannelError, ChannelUnavailable, OutreachContent
from app.infrastructure.threads_session import has_valid_session

# Threads posts cap at 500 characters. The DM limit is not documented and was not
# measured; 500 is the conservative floor. Raise it only after checking live.
_BODY_LIMIT = 500

_HANDLE_RE = re.compile(
    r"(?:https?://)?(?:www\.)?threads\.(?:com|net)/@?([\w.]+)", re.IGNORECASE)


def normalize_target(target: str) -> str:
    """'@nick', 'nick', 'https://www.threads.com/@nick' -> 'nick'."""
    t = (target or "").strip()
    m = _HANDLE_RE.match(t)
    if m:
        t = m.group(1)
    return t.lstrip("@")


class ThreadsChannel:
    name = "threads"
    body_limit = _BODY_LIMIT
    needs_subject = False

    def __init__(self, state_path: str, headless: bool = False):
        self._state_path = state_path
        self._headless = headless
        self._pw = None
        self._browser = None
        self._page = None

    def start(self) -> None:
        # Guard before launching anything, exactly as the LinkedIn channel does: a
        # state file with no live `sessionid` browses as a guest and every DM dies
        # on the login wall. Login is `make login_threads`, never done mid-run.
        if not has_valid_session(self._state_path):
            raise ChannelUnavailable(
                "сессия Threads недействительна или отсутствует (нет живого "
                "sessionid) — выполни `make login_threads` и залогинься заново")

        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._headless)
        self._page = self._browser.new_context(
            storage_state=self._state_path).new_page()

    def stop(self) -> None:
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def send(self, target: str, content: OutreachContent) -> None:
        handle = normalize_target(target)
        if not handle:
            raise ChannelError(f"не разобрал хендл Threads из '{target}'")
        # content.attachment_path is intentionally ignored: see module docstring.
        self._deliver(handle, content.body)

    def _deliver(self, handle: str, body: str) -> None:
        """Open the DM composer for `handle` and send `body`.

        Selectors are pinned during the live acceptance step of Task 10 — a DM
        composer cannot be read without a logged-in account, so this is the one
        place in the feature whose DOM was not verifiable up front.
        """
        raise NotImplementedError(
            "DM-композер Threads не реализован: селекторы снимаются на живом "
            "залогиненном аккаунте (Task 10). До этого threads-лид без контакта "
            "в треде помечается `manual`.")
```

- [ ] **Step 7: Зарегистрировать и сконфигурировать**

7a. В `sender/app/config.py` в блок per-platform settings добавить:

```python
# Threads (Meta). Runs on an Instagram account, so automating it risks THAT
# account — use a separate (burner) Instagram, never your personal one: a
# disabled Instagram disables its Threads profile automatically.
THREADS_STATE_PATH = os.environ.get("THREADS_STATE_PATH", "sender/threads_state.json")
```

7b. В `platform_enabled` добавить перед `return False`:

```python
    if platform == "threads":
        return True  # browser login is interactive; always available
```

7c. В `registry.py::build_channel` добавить перед `raise ValueError`:

```python
    if platform == "threads":
        return ThreadsChannel(config.THREADS_STATE_PATH, config.BROWSER_HEADLESS)
```

И импорт наверху файла:

```python
from app.infrastructure.channels.threads import ThreadsChannel
```

7d. В `sender/tests/test_channel_contract.py` добавить канал в список и в множество имён:

```python
from app.infrastructure.channels.threads import ThreadsChannel

_CHANNELS = [
    EmailChannel("h", 587, "u", "p", "Me"),
    HeadHunterChannel("hh.json", True),
    LinkedInChannel("l.json", True),
    WellfoundChannel("http://127.0.0.1:9222"),
    ThreadsChannel("t.json", True),
    # TelegramChannel constructs a TelegramClient; skip instantiation, check class attrs.
]
```

```python
    assert ch.name in {"telegram", "linkedin", "hh", "email", "wellfound", "threads"}
```

- [ ] **Step 8: Прогнать весь набор sender**

Run: `make test-unit`
Expected: PASS — включая `test_registry.py`, `test_config_platforms.py`, `test_channel_contract.py`.

- [ ] **Step 9: Коммит**

```bash
git add sender/app/infrastructure/threads_session.py \
        sender/app/infrastructure/channels/threads.py \
        sender/app/infrastructure/channels/registry.py sender/app/config.py \
        sender/tests/test_threads_session.py sender/tests/test_threads_channel.py \
        sender/tests/test_channel_contract.py
git commit -m "feat(send): канал Threads и проверка живой сессии"
```

---

### Task 10: Sender — логин, документация, живая приёмка

**Files:**
- Modify: `sender/app/application/login.py:9` (`LOGIN_ORDER`)
- Modify: `sender/app/interface/cli.py` (`run_login_threads`, `run_login_all`)
- Modify: `sender/run.py:16-24` и `:26-44`
- Modify: `Makefile` (цель + комментарий-шпаргалка + `.PHONY`)
- Modify: `sender/tests/test_login.py:51-53`
- Modify: `.env.example`, `README.md`
- Modify: `sender/app/infrastructure/channels/threads.py` (`_deliver` по живым селекторам)

**Interfaces:**
- Consumes: `has_valid_session` (Task 9), `ThreadsChannel` (Task 9).
- Produces: `run_login_threads()` в `cli.py`; `LOGIN_ORDER == ["telegram", "linkedin", "hh", "threads", "wellfound"]`.

- [ ] **Step 1: Обновить падающий тест логина**

В `sender/tests/test_login.py` заменить `test_platforms_needing_login_keeps_order_and_skips_existing` и добавить два новых:

```python
def test_platforms_needing_login_keeps_order_and_skips_existing():
    has = {"telegram": True, "linkedin": False, "hh": False, "threads": False,
           "wellfound": True}
    assert platforms_needing_login(has) == ["linkedin", "hh", "threads"]


def test_threads_is_in_the_login_order():
    assert "threads" in LOGIN_ORDER


def test_threads_logs_in_before_wellfound():
    """Wellfound's Chrome stays open for CDP and must stay last."""
    assert LOGIN_ORDER.index("threads") < LOGIN_ORDER.index("wellfound")
```

- [ ] **Step 2: Запустить и убедиться, что падает**

Run: `sender/.venv/bin/python -m pytest sender/tests/test_login.py -v`
Expected: FAIL — `AssertionError: assert ['linkedin', 'hh'] == ['linkedin', 'hh', 'threads']`

- [ ] **Step 3: Реализовать порядок логина**

В `sender/app/application/login.py:9`:

```python
# `make login` walks this list; wellfound goes last — its Chrome stays open (CDP).
LOGIN_ORDER = ["telegram", "linkedin", "hh", "threads", "wellfound"]
```

- [ ] **Step 4: Запустить и убедиться, что проходит**

Run: `sender/.venv/bin/python -m pytest sender/tests/test_login.py -v`
Expected: PASS (включая существующий `test_wellfound_logs_in_last`)

- [ ] **Step 5: Добавить команду логина**

5a. В `sender/app/interface/cli.py` рядом с `run_login_browser` добавить:

```python
def run_login_threads():
    """One-time interactive Threads login; saves the browser session to a file.

    Use a SEPARATE (burner) Instagram account: Threads runs on Instagram, and a
    disabled Instagram disables its Threads profile automatically.
    """
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto("https://www.threads.com/login")
    print("Войди в Threads в открывшемся окне (через отдельный Instagram-аккаунт), "
          "затем нажми Enter здесь...")
    input()
    context.storage_state(path=config.THREADS_STATE_PATH)
    browser.close()
    pw.stop()

    from app.infrastructure.threads_session import has_valid_session
    if has_valid_session(config.THREADS_STATE_PATH):
        print(f"✅ Сессия Threads сохранена: {config.THREADS_STATE_PATH}")
    else:
        print("⚠️ Файл сохранён, но живого `sessionid` в нём нет — вход не удался. "
              "Проверь, что действительно залогинился, и повтори.")
```

5b. В `run_login_all` добавить threads в `has_session` и в `actions`:

```python
    from app.infrastructure.linkedin_session import has_valid_session
    from app.infrastructure.threads_session import (
        has_valid_session as threads_has_valid_session,
    )

    has_session = {
        "telegram": Path(telegram_session_file(config.SESSION_PATH)).exists(),
        # A LinkedIn state file can exist yet be logged out (no live li_at); that
        # is not a session to skip — re-login instead.
        "linkedin": has_valid_session(config.LINKEDIN_STATE_PATH),
        "hh": Path(config.HH_STATE_PATH).exists(),
        # Same trap as LinkedIn: a state file without a live sessionid is a guest.
        "threads": threads_has_valid_session(config.THREADS_STATE_PATH),
        "wellfound": cdp_alive(config.WELLFOUND_CDP_URL),
    }
```

```python
    actions = {"telegram": _login_telegram, "linkedin": run_login_browser,
               "hh": run_login_hh, "threads": run_login_threads,
               "wellfound": run_login_wellfound}
```

5c. В `sender/run.py` добавить `run_login_threads` в импорт и ветку:

```python
    elif cmd == ["login_threads"]:
        run_login_threads()
```

5d. В `Makefile` добавить цель, `.PHONY` и строку в шпаргалку:

```makefile
login_threads:
	$(PYTHON) sender/run.py login_threads
```

```
#   make login_threads  -> open the Threads login window, save the session (one-time; use a burner Instagram)
```

- [ ] **Step 6: Прогнать весь набор**

Run: `make test-unit && sender/.venv/bin/python -m pytest intake-bot/tests -v`
Expected: PASS — оба набора целиком.

- [ ] **Step 7: Коммит команды логина**

```bash
git add sender/app/application/login.py sender/app/interface/cli.py sender/run.py \
        Makefile sender/tests/test_login.py
git commit -m "feat(send): make login_threads и Threads в сводном логине"
```

- [ ] **Step 8: Живая приёмка резолвера**

Запустить из корня проекта:

```bash
sender/.venv/bin/python - <<'PY'
import sys, pathlib
sys.path.insert(0, str(pathlib.Path("sender").resolve()))
from app.domain.contact import detect_contact
from app.infrastructure.threads_thread import render_thread

URL = "https://www.threads.com/@lnkrnchk/post/DbL4LxBl6v9"
text = render_thread(URL, headless=True)
print(f"--- {len(text)} символов ---")
print(text)
print("--- контакт:", detect_contact(text))
PY
```

Expected:
- текст содержит и `Ищу Full Stack Developer`, и `Что важно`, и `Формат работы`
  (то есть корневой пост И самоответы автора);
- **не** содержит `Навайбкодили` (чужой реплай);
- `detect_contact` вернул `Contact(platform='telegram', target='@skyluckwalker')`.

Если пост к этому моменту удалён — взять любой другой публичный тред-вакансию с
самоответом автора и проверить те же три свойства. Если селекторы не сработали,
**остановиться и сообщить**: JS в `threads_thread.py` надо перепроверить, а не
ослаблять тесты.

- [ ] **Step 9: Снять селекторы DM-композера и дописать `_deliver`**

Только после `make login_threads` на burner-аккаунте. Открыть композер вручную,
снять селекторы поля ввода и кнопки отправки, заменить `NotImplementedError` в
`ThreadsChannel._deliver` реальной реализацией по образцу
`channels/linkedin.py::fill_and_send` (комментарий с датой проверки обязателен),
и дописать в `sender/tests/test_threads_channel.py` тест на поддельной странице,
что `_deliver` кликает и печатает по этим селекторам.

Если DM-композер недоступен (аккаунт слишком свежий, требуется подтверждение),
**оставить `NotImplementedError`**: `SendOutreach` поймает его, лид получит статус
`manual` с заметкой — это допустимый исход по спеку, и он не `skipped`.

- [ ] **Step 10: Документация**

10a. В `.env.example` в блок per-platform добавить:

```
# Threads (Meta). ВНИМАНИЕ: Threads работает на аккаунте Instagram, поэтому
# автоматизация рискует ИМЕННО ИМ. Используй ОТДЕЛЬНЫЙ (burner) Instagram, не свой
# основной: отключённый Instagram автоматически отключает и его профиль Threads.
# Вход один раз: make login_threads
THREADS_STATE_PATH=sender/threads_state.json
```

10b. В `README.md`:
- в таблицу «Платформы» добавить строку Threads: «Один раз `make login_threads`
  (браузерный вход). Ссылку на тред кидаешь боту как обычную вакансию — бот сам
  дочитает тред и найдёт контакт для отклика»;
- в «Шпаргалку по командам» добавить `make login_threads`;
- в блок `[!CAUTION]` про риск блокировки добавить абзац: Threads сидит на
  Instagram-аккаунте, отключение Instagram отключает Threads автоматически, а в
  волнах банов Meta связанные аккаунты падали вместе — поэтому только отдельный
  аккаунт;
- в описание интейка (шаг 10, пункт 8) добавить Threads в перечень распознаваемых
  ссылок.

10c. Убедиться, что `threads_state.json` не попадёт в git:

Run: `git check-ignore -v sender/threads_state.json`
Expected: строка с правилом из `.gitignore`. Если пусто — добавить
`sender/threads_state.json` в `.gitignore` (сессия содержит cookie аккаунта).

- [ ] **Step 11: Финальный прогон и коммит**

Run: `make test-unit && sender/.venv/bin/python -m pytest intake-bot/tests -v`
Expected: PASS

```bash
git add .env.example README.md .gitignore \
        sender/app/infrastructure/channels/threads.py sender/tests/test_threads_channel.py
git commit -m "docs: Threads в README и .env.example, предупреждение про burner-аккаунт"
```
