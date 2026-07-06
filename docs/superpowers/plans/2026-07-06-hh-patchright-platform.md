# HH (hh.ru) Platform via Patchright — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the dead hh.ru API channel with patchright UI automation and add hh.ru as a search platform, plugged into the existing search → Кандидаты → approve → send pipeline with a single one-time login.

**Architecture:** Mirror the Wellfound pattern: a module-level DOM function (`apply_via_page` / `parse_hh_cards`) isolated from the browser-lifecycle class, patchright + real Chrome channel to pass hh.ru's anti-bot, session persisted to `HH_STATE_PATH` and shared by searcher and channel. The channel keeps an interactive login fallback (send runs are interactive); the searcher does NOT (the worker runs unattended) — it raises and tells the user to run `make login_hh`.

**Tech Stack:** Python 3.11+, patchright (already a dependency — used by Wellfound/WWR), pytest, Google Sheets via existing repos. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-06-hh-patchright-platform-design.md`

## Global Constraints

- Run all sender tests from the project root: `sender/.venv/Scripts/python.exe -m pytest sender/tests -v` (this is `make test-unit`).
- Run intake-bot tests from `intake-bot/`: `cd intake-bot && ../sender/.venv/Scripts/python.exe -m pytest tests -v`.
- No real browser in unit tests — fake pages/cards only.
- hh.ru selectors live in module-level `SEL_*` constants only (they drift; one place to fix). They are best-effort until Task 8 verifies them against the live site.
- Platform name is exactly `"hh"` everywhere (already used by leads/config).
- Russian user-facing strings, English code comments (project convention).
- Commit after every task.

---

### Task 1: Config — `HH_STATE_PATH`, `platform_enabled("hh")`

**Files:**
- Modify: `sender/app/config.py` (lines ~76-80 state-path block; lines ~143-145 HeadHunter block; `platform_enabled`)
- Test: `sender/tests/test_config_platforms.py`

**Interfaces:**
- Produces: `config.HH_STATE_PATH: str` (default `<root>/sender/hh_state.json`), `platform_enabled("hh") -> True`. `HH_ACCESS_TOKEN` / `HH_RESUME_ID` are GONE — later tasks must not reference them.

- [ ] **Step 1: Write the failing tests** — append to `sender/tests/test_config_platforms.py`:

```python
def test_hh_always_enabled_browser_login():
    # Browser login is interactive (make login_hh); no env vars required.
    assert platform_enabled("hh", {}) is True


def test_hh_state_path_configured():
    from app import config
    assert config.HH_STATE_PATH.endswith("hh_state.json")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_config_platforms.py -v`
Expected: `test_hh_always_enabled_browser_login` FAILS (`platform_enabled("hh", {})` is `False` — empty env has no token), `test_hh_state_path_configured` FAILS with `AttributeError: HH_STATE_PATH`.

- [ ] **Step 3: Implement config changes** in `sender/app/config.py`:

Replace the HeadHunter block:

```python
# HeadHunter
HH_ACCESS_TOKEN = os.environ.get("HH_ACCESS_TOKEN", "")
HH_RESUME_ID = os.environ.get("HH_RESUME_ID", "")
```

with:

```python
# HeadHunter (browser session; the applicant API was closed on 2025-12-15)
HH_STATE_PATH = os.environ.get(
    "HH_STATE_PATH", str(_ROOT / "sender" / "hh_state.json"))
```

In `platform_enabled`, replace:

```python
    if platform == "hh":
        return bool(env.get("HH_ACCESS_TOKEN") and env.get("HH_RESUME_ID"))
```

with:

```python
    if platform == "hh":
        return True  # browser login is interactive; always available
```

- [ ] **Step 4: Run the full sender suite** — expect the two new tests to PASS. `test_registry.py` / `test_channel_contract.py` still pass because the old `HeadHunterChannel(access_token, resume_id)` constructor is untouched until Task 2 (`build_channel("hh")` reads `_Cfg.HH_ACCESS_TOKEN`, which the test class still defines).

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add sender/app/config.py sender/tests/test_config_platforms.py
git commit -m "feat(hh): HH_STATE_PATH config, hh always enabled (browser login)"
```

---

### Task 2: Rewrite `HeadHunterChannel` on patchright

**Files:**
- Rewrite: `sender/app/infrastructure/channels/headhunter.py`
- Rewrite: `sender/tests/test_headhunter_channel.py`

**Interfaces:**
- Produces: `HeadHunterChannel(storage_state_path: str, headless: bool = False)` with `name="hh"`, `body_limit=10000`, `needs_subject=False`, `start()/stop()/send(target, content)`; module functions `extract_vacancy_id(target) -> str`, `vacancy_url(target) -> str`, `apply_via_page(page, url, content) -> None`; selector constants `SEL_APPLY`, `SEL_ALREADY_APPLIED`, `SEL_RELOCATION_CONFIRM`, `SEL_LETTER_TOGGLE`, `SEL_LETTER_INPUT`, `SEL_SUBMIT`.
- Consumes: `ChannelError`, `RateLimitedError`, `OutreachContent` from `app.domain.channel` (existing).

- [ ] **Step 1: Rewrite the test file** — replace the whole content of `sender/tests/test_headhunter_channel.py`:

```python
import pytest

from app.domain.channel import ChannelError, OutreachContent, RateLimitedError
from app.infrastructure.channels.headhunter import (
    SEL_ALREADY_APPLIED,
    SEL_APPLY,
    SEL_LETTER_INPUT,
    SEL_LETTER_TOGGLE,
    SEL_SUBMIT,
    HeadHunterChannel,
    apply_via_page,
    extract_vacancy_id,
    vacancy_url,
)


class _FakePage:
    """Maps selector -> element count; records goto/click/fill actions."""

    def __init__(self, counts, url="https://hh.ru/vacancy/1"):
        self._counts = counts
        self.url = url
        self.actions = []

    def goto(self, url, **kw):
        self.actions.append(("goto", url))

    def locator(self, selector):
        page = self

        class _Locator:
            def count(self_inner):
                return page._counts.get(selector, 0)

            @property
            def first(self_inner):
                return self_inner

            def click(self_inner):
                page.actions.append(("click", selector))

            def fill(self_inner, value):
                page.actions.append(("fill", selector, value))

        return _Locator()


def test_extract_vacancy_id_from_url():
    assert extract_vacancy_id("https://hh.ru/vacancy/12345?from=x") == "12345"
    assert extract_vacancy_id("12345") == "12345"


def test_extract_vacancy_id_supports_hh_kz():
    assert extract_vacancy_id("https://hh.kz/vacancy/777") == "777"


def test_extract_vacancy_id_invalid():
    with pytest.raises(ChannelError):
        extract_vacancy_id("https://hh.ru/employer/9")


def test_vacancy_url_builds_canonical_link():
    assert vacancy_url("https://hh.kz/vacancy/777?from=x") == "https://hh.ru/vacancy/777"


def test_apply_fills_letter_and_submits():
    page = _FakePage({SEL_APPLY: 1, SEL_LETTER_TOGGLE: 1,
                      SEL_LETTER_INPUT: 1, SEL_SUBMIT: 1})
    apply_via_page(page, "https://hh.ru/vacancy/1", OutreachContent(body="Здравствуйте"))
    assert ("goto", "https://hh.ru/vacancy/1") in page.actions
    assert ("click", SEL_APPLY) in page.actions
    assert ("click", SEL_LETTER_TOGGLE) in page.actions
    assert ("fill", SEL_LETTER_INPUT, "Здравствуйте") in page.actions
    assert ("click", SEL_SUBMIT) in page.actions


def test_apply_without_letter_toggle_fills_directly():
    # Some vacancies show the letter textarea right away (no toggle).
    page = _FakePage({SEL_APPLY: 1, SEL_LETTER_INPUT: 1, SEL_SUBMIT: 1})
    apply_via_page(page, "https://hh.ru/vacancy/2", OutreachContent(body="hi"))
    assert ("fill", SEL_LETTER_INPUT, "hi") in page.actions
    assert ("click", SEL_SUBMIT) in page.actions


def test_apply_raises_when_already_applied():
    page = _FakePage({SEL_ALREADY_APPLIED: 1})
    with pytest.raises(ChannelError, match="already applied"):
        apply_via_page(page, "https://hh.ru/vacancy/1", OutreachContent(body="hi"))


def test_apply_raises_without_apply_button():
    page = _FakePage({})
    with pytest.raises(ChannelError, match="no apply button"):
        apply_via_page(page, "https://hh.ru/vacancy/1", OutreachContent(body="hi"))


def test_login_redirect_raises_rate_limited():
    page = _FakePage({SEL_APPLY: 1}, url="https://hh.ru/account/login?backurl=%2F")
    with pytest.raises(RateLimitedError):
        apply_via_page(page, "https://hh.ru/vacancy/1", OutreachContent(body="hi"))


def test_channel_metadata():
    ch = HeadHunterChannel("hh.json", True)
    assert ch.name == "hh"
    assert ch.body_limit == 10000
    assert ch.needs_subject is False
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_headhunter_channel.py -v`
Expected: FAIL at import (`cannot import name 'SEL_APPLY'`).

- [ ] **Step 3: Rewrite the channel** — replace the whole content of `sender/app/infrastructure/channels/headhunter.py`:

```python
"""HeadHunter channel: applies to a vacancy via a logged-in browser session.

hh.ru closed its applicant API on 2025-12-15, so UI automation is the only
working path. Automating hh.ru violates its ToS and risks an account ban
(accepted by the user). Stock Playwright is fingerprinted by hh.ru's
anti-bot, so we use patchright + the real Chrome channel (same as Wellfound).
DOM interaction is isolated in apply_via_page() because selectors drift.
"""
import re

from app.domain.channel import ChannelError, OutreachContent, RateLimitedError

_VACANCY_RE = re.compile(r"hh\.(?:ru|kz)/vacancy/(\d+)")

# hh.ru data-qa hooks (verified live in Task 8; fix HERE when they drift).
SEL_APPLY = "[data-qa='vacancy-response-link-top']"
SEL_ALREADY_APPLIED = "[data-qa='vacancy-response-link-view-topic']"
SEL_RELOCATION_CONFIRM = "[data-qa='relocation-warning-confirm']"
SEL_LETTER_TOGGLE = "[data-qa='vacancy-response-letter-toggle']"
SEL_LETTER_INPUT = "[data-qa='vacancy-response-popup-form-letter-input']"
SEL_SUBMIT = "[data-qa='vacancy-response-submit-popup']"
_LOGIN_MARKERS = ("/account/login", "/login", "captcha")


def extract_vacancy_id(target: str) -> str:
    t = target.strip()
    if t.isdigit():
        return t
    m = _VACANCY_RE.search(t)
    if not m:
        raise ChannelError(f"cannot extract hh.ru vacancy id from: {target}")
    return m.group(1)


def vacancy_url(target: str) -> str:
    return f"https://hh.ru/vacancy/{extract_vacancy_id(target)}"


def _check_not_blocked(page) -> None:
    if any(marker in page.url for marker in _LOGIN_MARKERS):
        raise RateLimitedError(f"hh.ru asks to log in / solve captcha: {page.url}")


def apply_via_page(page, url: str, content: OutreachContent) -> None:
    page.goto(url, wait_until="domcontentloaded")
    _check_not_blocked(page)
    if page.locator(SEL_ALREADY_APPLIED).count() > 0:
        raise ChannelError(f"already applied: {url}")
    apply_btn = page.locator(SEL_APPLY)
    if apply_btn.count() == 0:
        raise ChannelError(f"no apply button on {url}")
    apply_btn.first.click()
    _check_not_blocked(page)
    # Foreign-vacancy confirmation popup ("вакансия в другой стране") — optional.
    if page.locator(SEL_RELOCATION_CONFIRM).count() > 0:
        page.locator(SEL_RELOCATION_CONFIRM).first.click()
    # The cover-letter textarea may need expanding first — also optional.
    if page.locator(SEL_LETTER_TOGGLE).count() > 0:
        page.locator(SEL_LETTER_TOGGLE).first.click()
    page.locator(SEL_LETTER_INPUT).first.fill(content.body)
    page.locator(SEL_SUBMIT).first.click()


class HeadHunterChannel:
    name = "hh"
    body_limit = 10000          # hh.ru cover-letter length limit
    needs_subject = False

    def __init__(self, storage_state_path: str, headless: bool = False):
        self._storage_state_path = storage_state_path
        self._headless = headless
        self._pw = None
        self._browser = None
        self._page = None

    def start(self) -> None:
        from pathlib import Path

        from patchright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._headless, channel="chrome")
        state = self._storage_state_path if Path(self._storage_state_path).exists() else None
        context = self._browser.new_context(storage_state=state, no_viewport=True)
        self._page = context.new_page()
        if state is None:
            self._page.goto("https://hh.ru/account/login")
            input("Залогинься в hh.ru в открытом окне, потом нажми Enter здесь...")
            context.storage_state(path=self._storage_state_path)

    def stop(self) -> None:
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def send(self, target: str, content: OutreachContent) -> None:
        if self._page is None:
            raise ChannelError("HeadHunterChannel.start() not called")
        apply_via_page(self._page, vacancy_url(target), content)
```

- [ ] **Step 4: Run the channel tests**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_headhunter_channel.py -v`
Expected: all PASS. (`test_registry.py` / `test_channel_contract.py` are now BROKEN — fixed in Task 3; run only this file here.)

- [ ] **Step 5: Commit**

```bash
git add sender/app/infrastructure/channels/headhunter.py sender/tests/test_headhunter_channel.py
git commit -m "feat(hh): rewrite HeadHunterChannel on patchright UI automation"
```

---

### Task 3: Channel registry + contract tests

**Files:**
- Modify: `sender/app/infrastructure/channels/registry.py` (the `"hh"` branch)
- Modify: `sender/tests/test_registry.py` (`_Cfg`)
- Modify: `sender/tests/test_channel_contract.py` (`_CHANNELS`)

**Interfaces:**
- Consumes: `HeadHunterChannel(storage_state_path, headless)` from Task 2, `config.HH_STATE_PATH` from Task 1.

- [ ] **Step 1: Update the tests.** In `sender/tests/test_registry.py`, in `_Cfg` replace the line `HH_ACCESS_TOKEN = "t"; HH_RESUME_ID = "r"` with:

```python
    HH_STATE_PATH = "hh.json"
```

In `sender/tests/test_channel_contract.py`, in `_CHANNELS` replace `HeadHunterChannel("t", "r"),` with:

```python
    HeadHunterChannel("hh.json", True),
```

- [ ] **Step 2: Run to verify current registry fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_registry.py sender/tests/test_channel_contract.py -v`
Expected: `test_build_hh_channel` FAILS (`_Cfg` has no `HH_ACCESS_TOKEN`); contract tests PASS already.

- [ ] **Step 3: Update the registry.** In `sender/app/infrastructure/channels/registry.py` replace:

```python
    if platform == "hh":
        return HeadHunterChannel(config.HH_ACCESS_TOKEN, config.HH_RESUME_ID)
```

with:

```python
    if platform == "hh":
        return HeadHunterChannel(config.HH_STATE_PATH, config.BROWSER_HEADLESS)
```

- [ ] **Step 4: Run the full sender suite**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add sender/app/infrastructure/channels/registry.py sender/tests/test_registry.py sender/tests/test_channel_contract.py
git commit -m "feat(hh): build_channel('hh') uses browser state, not API tokens"
```

---

### Task 4: `HHSearcher`

**Files:**
- Create: `sender/app/infrastructure/search/hh_search.py`
- Create: `sender/tests/test_hh_search.py`

**Interfaces:**
- Produces: `HHSearcher(storage_state_path: str, headless: bool = False)` with `name="hh"`, `start()/stop()`, `search(keywords_list, location, limit) -> list[Candidate]`, `describe(url) -> str`; module functions `build_search_url(query, page=0) -> str`, `parse_hh_cards(cards, limit) -> list[Candidate]`. `start()` raises `RuntimeError` mentioning `login_hh` when the state file is missing (the worker must never block on `input()`).
- Consumes: `Candidate`, `KIND_JOB`, `normalize_url` from `app.domain.candidate`.
- Card adapter contract (same as WWR): `card.get_text(role)` for roles `"title" | "company" | "salary" | "location"`, `card.get_href()`.

Design note: unlike WWR we do NOT re-filter titles with `title_matches` — hh.ru's own query engine already filtered, and relevant vacancies often have Russian titles the English keywords would drop.

- [ ] **Step 1: Write the failing tests** — create `sender/tests/test_hh_search.py`:

```python
import pytest

from app.infrastructure.search.hh_search import (
    HHSearcher,
    build_search_url,
    parse_hh_cards,
)


class _Card:
    def __init__(self, title, href, company="Acme", salary="", location="Almaty"):
        self._d = {"title": title, "company": company,
                   "salary": salary, "location": location}
        self._href = href

    def get_text(self, role):
        return self._d[role]

    def get_href(self):
        return self._href


def test_build_search_url_quotes_query_and_page():
    assert build_search_url("junior python", 1) == \
        "https://hh.ru/search/vacancy?text=junior%20python&page=1"


def test_parse_maps_cards_to_candidates():
    cards = [_Card("Junior Python", "https://hh.ru/vacancy/1?from=serp")]
    got = parse_hh_cards(cards, limit=10)
    assert len(got) == 1
    c = got[0]
    assert c.platform == "hh"
    assert c.kind == "job"
    assert c.title == "Junior Python"
    assert c.company == "Acme"
    assert c.url == "https://hh.ru/vacancy/1?from=serp"


def test_parse_skips_cards_without_title_or_url():
    cards = [_Card("", "https://hh.ru/vacancy/1"), _Card("Dev", "")]
    assert parse_hh_cards(cards, limit=10) == []


def test_parse_respects_limit():
    cards = [_Card(f"Dev {i}", f"https://hh.ru/vacancy/{i}") for i in range(5)]
    assert len(parse_hh_cards(cards, limit=3)) == 3


def test_searcher_metadata():
    s = HHSearcher("hh.json", headless=True)
    assert s.name == "hh"


def test_searcher_start_raises_without_state(tmp_path):
    s = HHSearcher(str(tmp_path / "missing.json"), headless=True)
    with pytest.raises(RuntimeError, match="login_hh"):
        s.start()
```

- [ ] **Step 2: Run to verify failure**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_hh_search.py -v`
Expected: FAIL with `ModuleNotFoundError: app.infrastructure.search.hh_search`.

- [ ] **Step 3: Implement** — create `sender/app/infrastructure/search/hh_search.py`:

```python
"""HeadHunter searcher via a logged-in patchright browser.

hh.ru's applicant API is closed and its pages sit behind an anti-bot that
flags stock Playwright, so we drive real Chrome via patchright with the
session saved by `make login_hh` (shared with the outreach channel). hh.ru's
own query engine does the filtering — we do NOT re-filter titles by keyword
(unlike WWR): relevant vacancies often have Russian titles. Raw DOM
extraction is isolated in _vacancy_cards / parse_hh_cards so selector drift
is easy to fix. start() refuses to run without a saved session instead of
prompting — the worker must never block on input().
"""
from urllib.parse import quote

from app.domain.candidate import KIND_JOB, Candidate, normalize_url

HH_BASE_URL = "https://hh.ru"
SEARCH_PAGES = 2  # first 1-2 result pages per keyword (spec)

# hh.ru data-qa hooks (verified live in Task 8; fix HERE when they drift).
SEL_CARD = "[data-qa='vacancy-serp__vacancy']"
SEL_TITLE = "[data-qa='serp-item__title']"
SEL_COMPANY = "[data-qa='vacancy-serp__vacancy-employer']"
SEL_SALARY = "[data-qa='vacancy-serp__vacancy-compensation']"
SEL_ADDRESS = "[data-qa='vacancy-serp__vacancy-address']"
SEL_DESCRIPTION = "[data-qa='vacancy-description']"


def build_search_url(query: str, page: int = 0) -> str:
    return f"{HH_BASE_URL}/search/vacancy?text={quote(query)}&page={page}"


def parse_hh_cards(cards, limit: int) -> list[Candidate]:
    out = []
    for card in cards:
        title = card.get_text("title")
        url = card.get_href()
        if not title or not url:
            continue
        out.append(Candidate(
            platform="hh", kind=KIND_JOB, url=url,
            title=title, company=card.get_text("company"),
            salary=card.get_text("salary"), location=card.get_text("location"),
            summary="",
        ))
        if len(out) >= limit:
            break
    return out


class _LiveCard:
    """Adapts a Playwright element's already-read text into the parser interface."""

    def __init__(self, title, company, salary, location, href):
        self._d = {"title": title, "company": company,
                   "salary": salary, "location": location}
        self._href = href or ""

    def get_text(self, role):
        return (self._d[role] or "").strip()

    def get_href(self):
        return self._href


class HHSearcher:
    name = "hh"

    def __init__(self, storage_state_path: str, headless: bool = False):
        self._storage_state_path = storage_state_path
        self._headless = headless
        self._pw = None
        self._browser = None
        self._page = None

    def start(self) -> None:
        from pathlib import Path

        if not Path(self._storage_state_path).exists():
            raise RuntimeError(
                f"hh.ru session not found at {self._storage_state_path}; "
                "run `make login_hh` first")

        from patchright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._headless, channel="chrome")
        context = self._browser.new_context(
            storage_state=self._storage_state_path, no_viewport=True)
        self._page = context.new_page()

    def stop(self) -> None:
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    @staticmethod
    def _text(el, selector):
        """First match's text, or '' — fast-fail so drift doesn't hang per card."""
        try:
            return el.locator(selector).first.inner_text(timeout=2000)
        except Exception:  # noqa: BLE001
            return ""

    def _vacancy_cards(self):
        cards = []
        for el in self._page.locator(SEL_CARD).all():
            try:
                href = el.locator(SEL_TITLE).first.get_attribute("href", timeout=2000)
            except Exception:  # noqa: BLE001
                href = ""
            cards.append(_LiveCard(
                title=self._text(el, SEL_TITLE),
                company=self._text(el, SEL_COMPANY),
                salary=self._text(el, SEL_SALARY),
                location=self._text(el, SEL_ADDRESS),
                href=href,
            ))
        return cards

    def search(self, keywords_list, location, limit) -> list[Candidate]:
        found: list[Candidate] = []
        seen: set[str] = set()
        for query in keywords_list:
            for page_n in range(SEARCH_PAGES):
                try:
                    self._page.goto(build_search_url(query, page_n),
                                    wait_until="domcontentloaded", timeout=30000)
                    self._page.wait_for_selector(SEL_CARD, timeout=12000)
                except Exception:  # noqa: BLE001 — one page failing must not kill the rest
                    break
                for c in parse_hh_cards(self._vacancy_cards(), limit):
                    key = normalize_url(c.url)
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    found.append(c)
                    if len(found) >= limit:
                        return found
        return found

    def describe(self, url: str) -> str:
        try:
            self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
            text = self._page.locator(SEL_DESCRIPTION).first.inner_text(timeout=15000)
            return text.strip()[:6000]
        except Exception:  # noqa: BLE001
            return ""
```

- [ ] **Step 4: Run the searcher tests**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_hh_search.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add sender/app/infrastructure/search/hh_search.py sender/tests/test_hh_search.py
git commit -m "feat(hh): HHSearcher via patchright (search + describe, no interactive login)"
```

---

### Task 5: Register `hh` as a search platform

**Files:**
- Modify: `sender/app/domain/search_request.py:10` (`SEARCH_PLATFORMS`)
- Modify: `sender/app/infrastructure/search/registry.py` (`build_searcher`)
- Modify: `sender/app/application/search_commands.py` (`_TOKEN_TO_PLATFORM`)
- Test: `sender/tests/test_search_platforms.py`, `sender/tests/test_search_registry.py`, `sender/tests/test_search_commands.py`

**Interfaces:**
- Consumes: `HHSearcher(storage_state_path, headless)` from Task 4, `config.HH_STATE_PATH` from Task 1.
- Produces: `"hh"` in `SEARCH_PLATFORMS`; `build_searcher("hh") -> HHSearcher`; `platforms_arg("search_hh") == ["hh"]`. The worker and `/start_search` pick `hh` up automatically (they iterate `SEARCH_PLATFORMS`).

- [ ] **Step 1: Write the failing tests.** Append to `sender/tests/test_search_platforms.py`:

```python
def test_search_platforms_includes_hh():
    assert "hh" in SEARCH_PLATFORMS
```

Append to `sender/tests/test_search_registry.py`:

```python
def test_build_hh():
    from app.infrastructure.search.hh_search import HHSearcher
    assert isinstance(build_searcher("hh"), HHSearcher)
```

Append to `sender/tests/test_search_commands.py` (import `platforms_arg` at top if not already imported there):

```python
def test_search_hh_token_maps_to_hh():
    assert platforms_arg("search_hh") == ["hh"]
```

- [ ] **Step 2: Run to verify failure**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_search_platforms.py sender/tests/test_search_registry.py sender/tests/test_search_commands.py -v`
Expected: the three new tests FAIL (`"hh" not in list`, `ValueError: no searcher`, `KeyError: 'search_hh'`).

- [ ] **Step 3: Implement.** In `sender/app/domain/search_request.py` change:

```python
SEARCH_PLATFORMS = ["linkedin", "wellfound", "remoteok", "remotive", "wwr"]
```

to:

```python
SEARCH_PLATFORMS = ["linkedin", "wellfound", "remoteok", "remotive", "wwr", "hh"]
```

In `sender/app/infrastructure/search/registry.py` add an import `from app.infrastructure.search.hh_search import HHSearcher` (match the file's existing import style) and, before the final `raise`, add:

```python
    if platform == "hh":
        return HHSearcher(config.HH_STATE_PATH, headless=config.BROWSER_HEADLESS)
```

In `sender/app/application/search_commands.py` add to `_TOKEN_TO_PLATFORM`:

```python
    "search_hh": "hh",
```

- [ ] **Step 4: Run the full sender suite** (checks the `SEARCH_PLATFORMS`-iterating tests too)

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add sender/app/domain/search_request.py sender/app/infrastructure/search/registry.py sender/app/application/search_commands.py sender/tests/test_search_platforms.py sender/tests/test_search_registry.py sender/tests/test_search_commands.py
git commit -m "feat(hh): register hh in SEARCH_PLATFORMS, searcher registry, CLI tokens"
```

---

### Task 6: `make login_hh` / `make search_hh` (CLI + run.py + Makefile)

**Files:**
- Modify: `sender/app/interface/cli.py` (add `run_login_hh`)
- Modify: `sender/run.py` (dispatch)
- Modify: `Makefile` (targets, .PHONY, comment header)

**Interfaces:**
- Consumes: `HeadHunterChannel` (Task 2) — its `start()` does the interactive login when the state file is missing, so `run_login_hh` is just start/stop.
- Produces: `python run.py login_hh` and `python run.py search_hh`; `make login_hh`, `make search_hh`.

- [ ] **Step 1: Add `run_login_hh` to `sender/app/interface/cli.py`** (next to `run_login_wellfound`):

```python
def run_login_hh():
    """Open the hh.ru login window once; the saved session serves search AND send."""
    from app.infrastructure.channels.headhunter import HeadHunterChannel

    ch = HeadHunterChannel(config.HH_STATE_PATH, headless=False)
    print("Открываю окно входа в hh.ru. Если сессия уже есть — окно просто закроется.")
    ch.start()
    ch.stop()
    print(f"Готово. Сессия сохранена в {config.HH_STATE_PATH}.")
```

- [ ] **Step 2: Wire `sender/run.py`.** Add `run_login_hh` to the `from app.interface.cli import (...)` list, add a dispatch branch after `login_wellfound`, and add `"search_hh"` to the search-token tuple:

```python
    elif cmd == ["login_hh"]:
        run_login_hh()
    elif cmd and cmd[0] in ("search", "search_linkedin", "search_wellfound",
                            "search_remoteok", "search_remotive", "search_wwr",
                            "search_hh"):
```

- [ ] **Step 3: Update the `Makefile`.** Add to the comment header:

```
#   make login_hh        -> open the hh.ru login window, save the session (one-time)
#   make search_hh       -> one-shot HeadHunter search (needs make login_hh once)
```

Add `login_hh search_hh` to the `.PHONY` line, and add targets after `search_wwr`:

```makefile
login_hh:
	$(PYTHON) sender/run.py login_hh

search_hh:
	$(PYTHON) sender/run.py search_hh
```

(Makefile recipes are TAB-indented.)

- [ ] **Step 4: Verify wiring without a browser**

Run: `sender/.venv/Scripts/python.exe -c "import sys; sys.path.insert(0, 'sender'); from app.interface.cli import run_login_hh; from app.application.search_commands import platforms_arg; print(platforms_arg('search_hh'))"`
Expected: `['hh']` and no import errors. Also run the full suite: `sender/.venv/Scripts/python.exe -m pytest sender/tests -v` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add sender/app/interface/cli.py sender/run.py Makefile
git commit -m "feat(hh): make login_hh / make search_hh entry points"
```

---

### Task 7: Telegram bot integration (`/search_hh`)

**Files:**
- Modify: `intake-bot/app/domain/bot_commands.py` (`command_to_search_platform`)
- Modify: `sender/register_bot_menu.py` (`bot_commands_payload`)
- Modify: `intake-bot/api/webhook.py:213-214` (help text)
- Test: `intake-bot/tests/test_bot_commands.py`, `sender/tests/test_bot_menu_platforms.py`

**Interfaces:**
- Produces: `/search_hh` → control-tab request with platform `"hh"`; the worker (Task 5) executes it. `/start_search` already covers hh via `SEARCH_PLATFORMS`.

- [ ] **Step 1: Write the failing tests.** Append to `intake-bot/tests/test_bot_commands.py`:

```python
def test_search_hh_command():
    assert command_to_search_platform("/search_hh") == "hh"
```

Append to `sender/tests/test_bot_menu_platforms.py` (inside `test_menu_has_new_search_commands` or as a new test):

```python
def test_menu_has_hh_search_command():
    commands = {c["command"] for c in bot_commands_payload()}
    assert "search_hh" in commands
```

- [ ] **Step 2: Run to verify failure**

Run: `cd intake-bot && ../sender/.venv/Scripts/python.exe -m pytest tests/test_bot_commands.py -v` — new test FAILS (returns `None`).
Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_bot_menu_platforms.py -v` (from project root) — new test FAILS.

- [ ] **Step 3: Implement.** In `intake-bot/app/domain/bot_commands.py` add before the `/start_search` branch:

```python
    if t.startswith("/search_hh"):
        return "hh"
```

In `sender/register_bot_menu.py` add after the `search_wwr` entry:

```python
        {"command": "search_hh", "description": "Искать вакансии в HeadHunter"},
```

In `intake-bot/api/webhook.py` (help text, lines ~213-214) extend the platform list string with `/search_hh` — change `"/search_wellfound, /search_remoteok, /search_remotive. "` to `"/search_wellfound, /search_remoteok, /search_remotive, /search_hh. "`.

- [ ] **Step 4: Run both test suites**

Run: `cd intake-bot && ../sender/.venv/Scripts/python.exe -m pytest tests -v` — all PASS.
Run (from project root): `sender/.venv/Scripts/python.exe -m pytest sender/tests -v` — all PASS.

- [ ] **Step 5: Commit** (note: the bot menu change takes effect after `make bot_menu`; the webhook change after the next Vercel deploy — remind the user at handoff)

```bash
git add intake-bot/app/domain/bot_commands.py intake-bot/api/webhook.py sender/register_bot_menu.py intake-bot/tests/test_bot_commands.py sender/tests/test_bot_menu_platforms.py
git commit -m "feat(hh): /search_hh bot command + menu entry"
```

---

### Task 8: Live selector verification, README, manual E2E

This task needs the user at the keyboard (login + judgment on a real vacancy). No unit tests — it validates the `SEL_*` constants against the real site and fixes them in place.

**Files:**
- Possibly modify: `SEL_*` constants in `sender/app/infrastructure/channels/headhunter.py` and `sender/app/infrastructure/search/hh_search.py`
- Modify: `README.md` (HeadHunter row of the platforms table, ~line 322)

- [ ] **Step 1: One-time login.** Run `make login_hh`, let the user log in (SMS code), confirm `sender/hh_state.json` appears and `git status` does NOT show it (covered by `*_state.json` in `.gitignore`).

- [ ] **Step 2: Verify SEARCH selectors live.** Run `make search_hh`. If 0 candidates land in «Кандидаты», inspect the real DOM (Playwright MCP snapshot of `https://hh.ru/search/vacancy?text=python`, or `page.pause()`), correct `SEL_CARD` / `SEL_TITLE` / `SEL_COMPANY` / `SEL_SALARY` / `SEL_ADDRESS` in `hh_search.py`, re-run until candidates appear. Unit tests stay green (they don't touch selectors' values).

- [ ] **Step 3: Verify APPLY selectors live.** Open one found vacancy in the logged-in browser (or run one real send via `make run` on a single approved hh lead). Verify each of `SEL_APPLY`, `SEL_ALREADY_APPLIED`, `SEL_LETTER_TOGGLE`, `SEL_LETTER_INPUT`, `SEL_SUBMIT`, `SEL_RELOCATION_CONFIRM` against the live DOM; fix constants as needed. Confirm the response actually appears in the hh.ru «Отклики» list.

- [ ] **Step 4: Update README.** Replace the HeadHunter row in the platforms table:

```markdown
| **HeadHunter** | Один раз: `make login_hh` (браузерный вход). Соискательский API hh.ru закрыт с 15.12.2025, поэтому отклики идут через браузер — риск бана тот же, что и для других браузерных платформ. |
```

Also add `make login_hh` / `make search_hh` to any command list in README that enumerates `make search_*` targets.

- [ ] **Step 5: Full E2E + commit.** Chain: `/search_hh` in Telegram (or `make search_hh`) → candidate appears in «Кандидаты» → ✅ Approve in Telegram → row lands in the main tab with status `new` → `make run` sends the response → status `sent`. Then:

```bash
git add sender/app/infrastructure/channels/headhunter.py sender/app/infrastructure/search/hh_search.py README.md
git commit -m "feat(hh): verified live hh.ru selectors, README update"
```

Remind the user: run `make bot_menu` once to publish the new `/search_hh` menu entry, and redeploy intake-bot to Vercel for the webhook help text.
