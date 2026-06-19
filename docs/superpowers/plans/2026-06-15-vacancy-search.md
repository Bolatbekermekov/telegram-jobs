# Vacancy Search Automation (sub-project C) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A laptop worker scrapes LinkedIn + Wellfound for junior/intern roles into a «Кандидаты» sheet tab; from Telegram the user reviews 7 at a time and approves them into the main leads tab, which the existing sender drains.

**Architecture:** Scraper runs on the laptop (residential IP + saved Playwright session) and writes candidates to a separate tab. The Vercel webhook (phone side) reads/writes the sheet only — `/show_vacancies` (review, works laptop-off) and `/start_search` (fresh scrape, needs laptop). Laptop and webhook coordinate solely through two sheet tabs («Кандидаты», «Команды» + heartbeat).

**Tech Stack:** Python, Playwright (sync), gspread, FastAPI (webhook), pytest. Test interpreter: `sender/.venv/Scripts/python.exe`.

**Pre-done:** `*_state.json` is already gitignored (commit `6d6abb6`). The design spec is `docs/superpowers/specs/2026-06-15-vacancy-search-design.md`.

**Conventions for every task:** run tests with
`sender/.venv/Scripts/python.exe -m pytest <path> -v` (sender) or
`sender/.venv/Scripts/python.exe -m pytest intake-bot/tests -v` (intake — it has no venv of its own). Do NOT create or redirect to a `NUL` file. Commit at the end of each task with the shown message.

---

### Task 1: Candidate domain + pure helpers

**Files:**
- Create: `sender/app/domain/candidate.py`
- Test: `sender/tests/test_candidate_domain.py`

- [ ] **Step 1: Write the failing test**

```python
# sender/tests/test_candidate_domain.py
from app.domain.candidate import (
    Candidate, CANDIDATE_COLUMNS, normalize_url, linkedin_action_for_url,
)


def test_candidate_columns_order():
    assert CANDIDATE_COLUMNS == [
        "id", "Платформа", "Тип", "URL", "Title", "Company",
        "Salary", "Location", "Summary", "Статус", "Дата",
    ]


def test_normalize_url_lowercases_host_strips_query_fragment_slash():
    a = normalize_url("HTTPS://www.LinkedIn.com/jobs/view/123/?ref=abc#top")
    b = normalize_url("https://www.linkedin.com/jobs/view/123")
    assert a == b == "https://www.linkedin.com/jobs/view/123"


def test_normalize_url_handles_trailing_slash_only():
    assert normalize_url("https://wellfound.com/jobs/9/") == "https://wellfound.com/jobs/9"


def test_linkedin_action_for_url():
    assert linkedin_action_for_url("https://www.linkedin.com/jobs/view/1") == "easy_apply"
    assert linkedin_action_for_url("https://www.linkedin.com/in/jane-doe") == "dm"


def test_candidate_is_a_dataclass_with_fields():
    c = Candidate(platform="linkedin", kind="job", url="u", title="t",
                  company="c", salary="", location="Remote", summary="s")
    assert c.platform == "linkedin" and c.kind == "job" and c.salary == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_candidate_domain.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.domain.candidate'`

- [ ] **Step 3: Write minimal implementation**

```python
# sender/app/domain/candidate.py
"""Domain entities for vacancy search. No external dependencies."""
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

# Fixed column order of the «Кандидаты» sheet tab.
CANDIDATE_COLUMNS = [
    "id", "Платформа", "Тип", "URL", "Title", "Company",
    "Salary", "Location", "Summary", "Статус", "Дата",
]

STATUS_PENDING = "pending"
STATUS_TAKEN = "taken"
STATUS_REJECTED = "rejected"

KIND_JOB = "job"
KIND_PROFILE = "profile"


@dataclass
class Candidate:
    platform: str    # linkedin | wellfound
    kind: str        # job | profile
    url: str
    title: str
    company: str
    salary: str      # "" when the platform does not expose it
    location: str
    summary: str


def normalize_url(url: str) -> str:
    """Dedup key: lowercase host, drop query/fragment, strip trailing slash."""
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def linkedin_action_for_url(url: str) -> str:
    """`/jobs/` URLs are Easy-Apply targets; `/in/` URLs are recruiter DMs."""
    return "easy_apply" if "/jobs/" in url else "dm"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_candidate_domain.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add sender/app/domain/candidate.py sender/tests/test_candidate_domain.py
git commit -m "feat: Candidate domain + normalize_url/linkedin_action helpers"
```

---

### Task 2: SearchRequest domain

**Files:**
- Create: `sender/app/domain/search_request.py`
- Test: `sender/tests/test_search_request_domain.py`

- [ ] **Step 1: Write the failing test**

```python
# sender/tests/test_search_request_domain.py
from app.domain.search_request import (
    SearchRequest, REQ_PENDING, REQ_RUNNING, REQ_DONE, REQ_ERROR,
    platforms_for,
)


def test_status_constants():
    assert (REQ_PENDING, REQ_RUNNING, REQ_DONE, REQ_ERROR) == (
        "pending", "running", "done", "error")


def test_platforms_for_all_expands():
    assert platforms_for("all") == ["linkedin", "wellfound"]


def test_platforms_for_single():
    assert platforms_for("wellfound") == ["wellfound"]


def test_search_request_fields():
    r = SearchRequest(id="3", platform="all", status=REQ_PENDING)
    assert r.id == "3" and r.platform == "all" and r.status == "pending"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_search_request_domain.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.domain.search_request'`

- [ ] **Step 3: Write minimal implementation**

```python
# sender/app/domain/search_request.py
"""Search-request entity exchanged via the «Команды» tab. No external deps."""
from dataclasses import dataclass

REQ_PENDING = "pending"
REQ_RUNNING = "running"
REQ_DONE = "done"
REQ_ERROR = "error"

# Platforms searchable in sub-project C, in scrape order.
SEARCH_PLATFORMS = ["linkedin", "wellfound"]


@dataclass
class SearchRequest:
    id: str
    platform: str   # all | linkedin | wellfound
    status: str


def platforms_for(platform: str) -> list[str]:
    """Expand a request's platform field into the concrete platforms to scrape."""
    if platform == "all":
        return list(SEARCH_PLATFORMS)
    return [platform]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_search_request_domain.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add sender/app/domain/search_request.py sender/tests/test_search_request_domain.py
git commit -m "feat: SearchRequest domain + platforms_for expansion"
```

---

### Task 3: Config — search settings

**Files:**
- Modify: `sender/app/config.py` (append a new section after line 80, the `BROWSER_HEADLESS` line)
- Test: `sender/tests/test_search_config.py`

- [ ] **Step 1: Write the failing test**

```python
# sender/tests/test_search_config.py
from app import config


def test_search_defaults_present():
    assert config.SEARCH_KEYWORDS == ["internship", "junior"]
    assert config.SEARCH_LOCATION == "Worldwide"
    assert config.SEARCH_LIMIT_PER_PLATFORM == 15
    assert config.SHOW_BATCH == 7
    assert config.WORKER_POLL_SECONDS == 60
    assert config.HEARTBEAT_STALE_SECONDS == 180
    assert config.LINKEDIN_PEOPLE_ENABLED is False
    assert config.PACING_MIN_SECONDS < config.PACING_MAX_SECONDS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_search_config.py -v`
Expected: FAIL with `AttributeError: module 'app.config' has no attribute 'SEARCH_KEYWORDS'`

- [ ] **Step 3: Write minimal implementation**

Append to `sender/app/config.py` (after the `BROWSER_HEADLESS = ...` line):

```python

# --- Vacancy search (sub-project C) ---
SEARCH_KEYWORDS = [
    k.strip() for k in os.environ.get("SEARCH_KEYWORDS", "internship,junior").split(",")
    if k.strip()
]
SEARCH_LOCATION = os.environ.get("SEARCH_LOCATION", "Worldwide")
SEARCH_LIMIT_PER_PLATFORM = int(os.environ.get("SEARCH_LIMIT_PER_PLATFORM", "15"))
SHOW_BATCH = int(os.environ.get("SHOW_BATCH", "7"))
WORKER_POLL_SECONDS = int(os.environ.get("WORKER_POLL_SECONDS", "60"))
HEARTBEAT_STALE_SECONDS = int(os.environ.get("HEARTBEAT_STALE_SECONDS", "180"))
# Recruiter-profile (DM) search is fragile/ban-prone; off by default.
LINKEDIN_PEOPLE_ENABLED = os.environ.get("LINKEDIN_PEOPLE_ENABLED", "false").lower() == "true"
# Human-like delay between scrape actions.
PACING_MIN_SECONDS = int(os.environ.get("PACING_MIN_SECONDS", "2"))
PACING_MAX_SECONDS = int(os.environ.get("PACING_MAX_SECONDS", "6"))
# Sheet tabs used for search coordination.
CANDIDATES_TAB = os.environ.get("CANDIDATES_TAB", "Кандидаты")
CONTROL_TAB = os.environ.get("CONTROL_TAB", "Команды")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_search_config.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add sender/app/config.py sender/tests/test_search_config.py
git commit -m "feat: search settings in sender config"
```

---

### Task 4: LinkedIn searcher (URL builder + pure DOM parse + Playwright class)

**Files:**
- Create: `sender/app/infrastructure/search/__init__.py` (empty)
- Create: `sender/app/infrastructure/search/linkedin_search.py`
- Test: `sender/tests/test_linkedin_search.py`

DOM extraction is isolated in pure `parse_*` functions (selectors drift). The class wraps a logged-in Playwright session like the existing channels. Tests drive the parsers with fake page objects — no browser.

- [ ] **Step 1: Write the failing test**

```python
# sender/tests/test_linkedin_search.py
from app.infrastructure.search.linkedin_search import (
    build_jobs_url, parse_job_cards, parse_people_cards,
)


def test_build_jobs_url_has_filters():
    url = build_jobs_url("junior developer", "Worldwide")
    assert "linkedin.com/jobs/search" in url
    assert "keywords=junior+developer" in url or "keywords=junior%20developer" in url
    assert "f_E=1%2C2" in url or "f_E=1,2" in url   # intern + entry
    assert "f_WT=2" in url                            # remote
    assert "f_TPR=r86400" in url                      # last 24h


class _FakeCard:
    def __init__(self, title, company, location, href):
        self._d = {"title": title, "company": company, "location": location, "href": href}

    def get_text(self, role):
        return self._d[role]

    def get_href(self):
        return self._d["href"]


def test_parse_job_cards_maps_to_candidates():
    cards = [_FakeCard("Junior Backend Engineer", "Acme", "Remote",
                       "https://www.linkedin.com/jobs/view/123")]
    out = parse_job_cards(cards, limit=10)
    assert len(out) == 1
    c = out[0]
    assert c.platform == "linkedin" and c.kind == "job"
    assert c.title == "Junior Backend Engineer" and c.company == "Acme"
    assert c.location == "Remote" and c.salary == ""
    assert c.url == "https://www.linkedin.com/jobs/view/123"


def test_parse_job_cards_respects_limit():
    cards = [_FakeCard(f"t{i}", "c", "Remote", f"https://www.linkedin.com/jobs/view/{i}")
             for i in range(5)]
    assert len(parse_job_cards(cards, limit=3)) == 3


def test_parse_people_cards_maps_profiles():
    cards = [_FakeCard("Jane Recruiter", "Tech Recruiter @ Acme", "",
                       "https://www.linkedin.com/in/jane")]
    out = parse_people_cards(cards, limit=10)
    assert out[0].kind == "profile"
    assert out[0].title == "Jane Recruiter"
    assert out[0].company == "Tech Recruiter @ Acme"
    assert out[0].url == "https://www.linkedin.com/in/jane"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_linkedin_search.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.infrastructure.search'`

- [ ] **Step 3: Write minimal implementation**

Create empty `sender/app/infrastructure/search/__init__.py`, then:

```python
# sender/app/infrastructure/search/linkedin_search.py
"""LinkedIn vacancy/recruiter search via a logged-in Playwright session.

Automating LinkedIn violates its ToS and risks an account ban (accepted by the
user). Raw DOM extraction is isolated in parse_* (selectors drift); the class
collects "card" wrappers and hands them to the pure parsers.
"""
from urllib.parse import urlencode

from app.domain.candidate import Candidate, KIND_JOB, KIND_PROFILE


def build_jobs_url(keywords: str, location: str) -> str:
    qs = urlencode({
        "keywords": keywords,
        "location": location,
        "f_E": "1,2",       # 1=Internship, 2=Entry level
        "f_WT": "2",        # Remote
        "f_TPR": "r86400",  # posted in the last 24h
    })
    return f"https://www.linkedin.com/jobs/search/?{qs}"


def build_people_url(keywords: str) -> str:
    qs = urlencode({"keywords": keywords})
    return f"https://www.linkedin.com/search/results/people/?{qs}"


def parse_job_cards(cards, limit: int) -> list[Candidate]:
    out = []
    for card in cards[:limit]:
        out.append(Candidate(
            platform="linkedin", kind=KIND_JOB,
            url=card.get_href(),
            title=card.get_text("title"),
            company=card.get_text("company"),
            salary="",  # LinkedIn rarely exposes salary
            location=card.get_text("location"),
            summary="",
        ))
    return out


def parse_people_cards(cards, limit: int) -> list[Candidate]:
    out = []
    for card in cards[:limit]:
        out.append(Candidate(
            platform="linkedin", kind=KIND_PROFILE,
            url=card.get_href(),
            title=card.get_text("title"),
            company=card.get_text("company"),  # headline goes here
            salary="",
            location=card.get_text("location"),
            summary="",
        ))
    return out


class LinkedInSearcher:
    name = "linkedin"

    def __init__(self, storage_state_path: str, headless: bool = True,
                 people_enabled: bool = False):
        self._storage_state_path = storage_state_path
        self._headless = headless
        self._people_enabled = people_enabled
        self._pw = None
        self._browser = None
        self._page = None

    def start(self) -> None:
        from pathlib import Path

        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._headless)
        state = self._storage_state_path if Path(self._storage_state_path).exists() else None
        context = self._browser.new_context(storage_state=state)
        self._page = context.new_page()
        if state is None:
            self._page.goto("https://www.linkedin.com/login")
            input("Залогинься в LinkedIn в открытом окне, потом нажми Enter здесь...")
            context.storage_state(path=self._storage_state_path)

    def stop(self) -> None:
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def _job_cards(self):
        """Return card wrappers exposing get_text(role)/get_href(). Selectors here."""
        cards = []
        for el in self._page.locator("div.job-card-container").all():
            cards.append(_LiveCard(
                title=el.locator(".job-card-list__title").inner_text(),
                company=el.locator(".job-card-container__company-name").inner_text(),
                location=el.locator(".job-card-container__metadata-item").first.inner_text(),
                href=el.locator("a.job-card-list__title").first.get_attribute("href"),
            ))
        return cards

    def _people_cards(self):
        cards = []
        for el in self._page.locator("li.reusable-search__result-container").all():
            cards.append(_LiveCard(
                title=el.locator("span.entity-result__title-text a").first.inner_text(),
                company=el.locator(".entity-result__primary-subtitle").inner_text(),
                location="",
                href=el.locator("span.entity-result__title-text a").first.get_attribute("href"),
            ))
        return cards

    def search(self, keywords_list, location, limit) -> list[Candidate]:
        found: list[Candidate] = []
        for kw in keywords_list:
            self._page.goto(build_jobs_url(kw, location), wait_until="domcontentloaded")
            found += parse_job_cards(self._job_cards(), limit=limit)
            if self._people_enabled:
                self._page.goto(build_people_url(kw), wait_until="domcontentloaded")
                found += parse_people_cards(self._people_cards(), limit=limit)
        return found[:limit]


class _LiveCard:
    """Adapts a Playwright element's already-read text into the parser interface."""

    def __init__(self, title, company, location, href):
        self._d = {"title": title, "company": company, "location": location}
        self._href = href if str(href).startswith("http") else f"https://www.linkedin.com{href}"

    def get_text(self, role):
        return (self._d[role] or "").strip()

    def get_href(self):
        return self._href
```

- [ ] **Step 4: Run test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_linkedin_search.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add sender/app/infrastructure/search/__init__.py sender/app/infrastructure/search/linkedin_search.py sender/tests/test_linkedin_search.py
git commit -m "feat: LinkedIn searcher (URL builder + pure card parsers)"
```

---

### Task 5: Wellfound searcher (URL builder + pure DOM parse + Playwright class)

**Files:**
- Create: `sender/app/infrastructure/search/wellfound_search.py`
- Test: `sender/tests/test_wellfound_search.py`

- [ ] **Step 1: Write the failing test**

```python
# sender/tests/test_wellfound_search.py
from app.infrastructure.search.wellfound_search import build_jobs_url, parse_job_cards


def test_build_jobs_url_contains_query():
    url = build_jobs_url("junior")
    assert "wellfound.com" in url and "junior" in url


class _FakeCard:
    def __init__(self, d):
        self._d = d

    def get_text(self, role):
        return self._d.get(role, "")

    def get_href(self):
        return self._d["href"]


def test_parse_job_cards_keeps_salary():
    cards = [_FakeCard({"title": "Junior Dev", "company": "Acme", "salary": "$40k–55k",
                        "location": "Remote", "href": "https://wellfound.com/jobs/9"})]
    out = parse_job_cards(cards, limit=10)
    c = out[0]
    assert c.platform == "wellfound" and c.kind == "job"
    assert c.salary == "$40k–55k" and c.company == "Acme"
    assert c.url == "https://wellfound.com/jobs/9"


def test_parse_job_cards_blank_salary_ok():
    cards = [_FakeCard({"title": "t", "company": "c", "salary": "",
                        "location": "Remote", "href": "https://wellfound.com/jobs/1"})]
    assert parse_job_cards(cards, limit=10)[0].salary == ""


def test_parse_respects_limit():
    cards = [_FakeCard({"title": "t", "company": "c", "salary": "", "location": "x",
                        "href": f"https://wellfound.com/jobs/{i}"}) for i in range(4)]
    assert len(parse_job_cards(cards, limit=2)) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_wellfound_search.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.infrastructure.search.wellfound_search'`

- [ ] **Step 3: Write minimal implementation**

```python
# sender/app/infrastructure/search/wellfound_search.py
"""Wellfound vacancy search via a logged-in Playwright session.

Automating Wellfound violates its ToS and risks a ban (accepted by the user).
DOM extraction isolated in parse_job_cards (selectors drift).
"""
from urllib.parse import urlencode

from app.domain.candidate import Candidate, KIND_JOB


def build_jobs_url(keyword: str) -> str:
    qs = urlencode({"q": keyword, "remote": "true"})
    return f"https://wellfound.com/jobs?{qs}"


def parse_job_cards(cards, limit: int) -> list[Candidate]:
    out = []
    for card in cards[:limit]:
        out.append(Candidate(
            platform="wellfound", kind=KIND_JOB,
            url=card.get_href(),
            title=card.get_text("title"),
            company=card.get_text("company"),
            salary=card.get_text("salary"),
            location=card.get_text("location"),
            summary="",
        ))
    return out


class WellfoundSearcher:
    name = "wellfound"

    def __init__(self, storage_state_path: str, headless: bool = True):
        self._storage_state_path = storage_state_path
        self._headless = headless
        self._pw = None
        self._browser = None
        self._page = None

    def start(self) -> None:
        from pathlib import Path

        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._headless)
        state = self._storage_state_path if Path(self._storage_state_path).exists() else None
        context = self._browser.new_context(storage_state=state)
        self._page = context.new_page()
        if state is None:
            self._page.goto("https://wellfound.com/login")
            input("Залогинься в Wellfound в открытом окне, потом нажми Enter здесь...")
            context.storage_state(path=self._storage_state_path)

    def stop(self) -> None:
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def _job_cards(self):
        cards = []
        for el in self._page.locator("div.styles_component__job").all():
            href = el.locator("a").first.get_attribute("href")
            cards.append(_LiveCard(
                title=el.locator("a.styles_titleLink__").first.inner_text(),
                company=el.locator("h2").first.inner_text(),
                salary=el.locator(".styles_compensation__").first.inner_text(),
                location=el.locator(".styles_location__").first.inner_text(),
                href=href if str(href).startswith("http") else f"https://wellfound.com{href}",
            ))
        return cards

    def search(self, keywords_list, location, limit) -> list[Candidate]:
        found: list[Candidate] = []
        for kw in keywords_list:
            self._page.goto(build_jobs_url(kw), wait_until="domcontentloaded")
            found += parse_job_cards(self._job_cards(), limit=limit)
        return found[:limit]


class _LiveCard:
    def __init__(self, title, company, salary, location, href):
        self._d = {"title": title, "company": company, "salary": salary, "location": location}
        self._href = href

    def get_text(self, role):
        return (self._d.get(role) or "").strip()

    def get_href(self):
        return self._href
```

- [ ] **Step 4: Run test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_wellfound_search.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add sender/app/infrastructure/search/wellfound_search.py sender/tests/test_wellfound_search.py
git commit -m "feat: Wellfound searcher (URL builder + pure card parser)"
```

---

### Task 6: Searcher registry

**Files:**
- Create: `sender/app/infrastructure/search/registry.py`
- Test: `sender/tests/test_search_registry.py`

- [ ] **Step 1: Write the failing test**

```python
# sender/tests/test_search_registry.py
import pytest

from app.infrastructure.search.registry import build_searcher
from app.infrastructure.search.linkedin_search import LinkedInSearcher
from app.infrastructure.search.wellfound_search import WellfoundSearcher


def test_build_linkedin():
    s = build_searcher("linkedin")
    assert isinstance(s, LinkedInSearcher)


def test_build_wellfound():
    s = build_searcher("wellfound")
    assert isinstance(s, WellfoundSearcher)


def test_unknown_platform_raises():
    with pytest.raises(ValueError):
        build_searcher("telegram")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_search_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.infrastructure.search.registry'`

- [ ] **Step 3: Write minimal implementation**

```python
# sender/app/infrastructure/search/registry.py
"""Build the right searcher for a platform (mirrors channels/registry.py)."""
from app import config
from app.infrastructure.search.linkedin_search import LinkedInSearcher
from app.infrastructure.search.wellfound_search import WellfoundSearcher


def build_searcher(platform: str):
    if platform == "linkedin":
        return LinkedInSearcher(
            config.LINKEDIN_STATE_PATH,
            headless=config.BROWSER_HEADLESS,
            people_enabled=config.LINKEDIN_PEOPLE_ENABLED,
        )
    if platform == "wellfound":
        return WellfoundSearcher(
            config.WELLFOUND_STATE_PATH,
            headless=config.BROWSER_HEADLESS,
        )
    raise ValueError(f"no searcher for platform: {platform}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_search_registry.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add sender/app/infrastructure/search/registry.py sender/tests/test_search_registry.py
git commit -m "feat: searcher registry"
```

---

### Task 7: Candidates repo — pure dedup/cap logic + row mapping

**Files:**
- Create: `sender/app/infrastructure/candidates_repo.py`
- Test: `sender/tests/test_candidates_repo.py`

The gspread I/O is a thin shell; the testable core is pure: `candidate_to_row`
and `should_add` (dedup + 15/platform cap). The class composes them.

- [ ] **Step 1: Write the failing test**

```python
# sender/tests/test_candidates_repo.py
from app.domain.candidate import Candidate, STATUS_PENDING
from app.infrastructure.candidates_repo import candidate_to_row, should_add


def _cand(url, platform="linkedin"):
    return Candidate(platform=platform, kind="job", url=url, title="t", company="c",
                     salary="", location="Remote", summary="s")


def test_candidate_to_row_positional():
    row = candidate_to_row(_cand("https://x/1"), row_id=4, now="2026-06-15 10:00")
    # id, Платформа, Тип, URL, Title, Company, Salary, Location, Summary, Статус, Дата
    assert row == [4, "linkedin", "job", "https://x/1", "t", "c", "", "Remote", "s",
                   STATUS_PENDING, "2026-06-15 10:00"]


def test_should_add_true_when_new_and_under_cap():
    assert should_add(_cand("https://x/1"), seen_keys=set(), platform_pending=0, cap=15)


def test_should_add_false_when_url_seen():
    seen = {"https://x/1"}
    assert not should_add(_cand("https://x/1/?ref=a"), seen_keys=seen,
                          platform_pending=0, cap=15)


def test_should_add_false_when_cap_reached():
    assert not should_add(_cand("https://x/2"), seen_keys=set(),
                          platform_pending=15, cap=15)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_candidates_repo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.infrastructure.candidates_repo'`

- [ ] **Step 3: Write minimal implementation**

```python
# sender/app/infrastructure/candidates_repo.py
"""«Кандидаты» tab repository: append candidates with dedup + per-platform cap."""
import datetime as _dt

from app.domain.candidate import (
    CANDIDATE_COLUMNS, STATUS_PENDING, Candidate, normalize_url,
)


def candidate_to_row(c: Candidate, row_id, now: str) -> list:
    """Positional row matching CANDIDATE_COLUMNS."""
    return [
        row_id, c.platform, c.kind, c.url, c.title, c.company,
        c.salary, c.location, c.summary, STATUS_PENDING, now,
    ]


def should_add(c: Candidate, seen_keys: set, platform_pending: int, cap: int) -> bool:
    """New (normalized URL unseen) and the platform is under its pending cap."""
    if platform_pending >= cap:
        return False
    return normalize_url(c.url) not in seen_keys


class CandidatesRepo:
    def __init__(self, worksheet, main_worksheet, cap: int):
        self._ws = worksheet          # «Кандидаты» tab
        self._main = main_worksheet   # main leads tab (for cross-tab dedup)
        self._cap = cap

    def _ensure_header(self) -> None:
        if self._ws.row_values(1) != CANDIDATE_COLUMNS:
            self._ws.update("A1", [CANDIDATE_COLUMNS])

    def _seen_keys(self) -> set:
        keys = set()
        for url in self._ws.col_values(CANDIDATE_COLUMNS.index("URL") + 1)[1:]:
            if url:
                keys.add(normalize_url(url))
        # main tab: «Цель» column holds the URL for linkedin/wellfound leads
        from app.domain.lead import COLUMNS as MAIN
        for tgt in self._main.col_values(MAIN.index("Цель") + 1)[1:]:
            if tgt and "http" in tgt:
                keys.add(normalize_url(tgt))
        return keys

    def _pending_counts(self) -> dict:
        plats = self._ws.col_values(CANDIDATE_COLUMNS.index("Платформа") + 1)[1:]
        stats = self._ws.col_values(CANDIDATE_COLUMNS.index("Статус") + 1)[1:]
        counts: dict = {}
        for p, s in zip(plats, stats):
            if s == STATUS_PENDING:
                counts[p] = counts.get(p, 0) + 1
        return counts

    def _next_id(self) -> int:
        return max(len(self._ws.col_values(1)) - 1, 0) + 1

    def add_new(self, candidates) -> int:
        """Append candidates that pass dedup + cap. Returns how many were added."""
        self._ensure_header()
        seen = self._seen_keys()
        counts = self._pending_counts()
        now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        added = 0
        for c in candidates:
            if not should_add(c, seen, counts.get(c.platform, 0), self._cap):
                continue
            self._ws.append_row(candidate_to_row(c, self._next_id(), now),
                                value_input_option="USER_ENTERED")
            seen.add(normalize_url(c.url))
            counts[c.platform] = counts.get(c.platform, 0) + 1
            added += 1
        return added
```

- [ ] **Step 4: Run test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_candidates_repo.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add sender/app/infrastructure/candidates_repo.py sender/tests/test_candidates_repo.py
git commit -m "feat: candidates repo with pure dedup/cap + row mapping"
```

---

### Task 8: Control repo — heartbeat staleness + request mapping

**Files:**
- Create: `sender/app/infrastructure/control_repo.py`
- Test: `sender/tests/test_control_repo.py`

- [ ] **Step 1: Write the failing test**

```python
# sender/tests/test_control_repo.py
import datetime as _dt

from app.domain.search_request import REQ_PENDING
from app.infrastructure.control_repo import is_stale, request_to_row, CONTROL_COLUMNS


def test_control_columns():
    assert CONTROL_COLUMNS == ["id", "platform", "status", "created_at", "done_at"]


def test_request_to_row():
    row = request_to_row(row_id=2, platform="all", now="2026-06-15 10:00")
    assert row == [2, "all", REQ_PENDING, "2026-06-15 10:00", ""]


def test_is_stale_true_when_old():
    now = _dt.datetime(2026, 6, 15, 10, 0, 0)
    last = "2026-06-15 09:50:00"   # 600s ago
    assert is_stale(last, now, threshold_seconds=180)


def test_is_stale_false_when_fresh():
    now = _dt.datetime(2026, 6, 15, 10, 0, 0)
    last = "2026-06-15 09:59:00"   # 60s ago
    assert not is_stale(last, now, threshold_seconds=180)


def test_is_stale_true_when_blank():
    now = _dt.datetime(2026, 6, 15, 10, 0, 0)
    assert is_stale("", now, threshold_seconds=180)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_control_repo.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.infrastructure.control_repo'`

- [ ] **Step 3: Write minimal implementation**

```python
# sender/app/infrastructure/control_repo.py
"""«Команды» tab: search requests + worker heartbeat.

Layout: row 1 = CONTROL_COLUMNS header; cell G1 holds the heartbeat timestamp.
Request rows live below the header.
"""
import datetime as _dt

from app.domain.search_request import REQ_PENDING, REQ_DONE, SearchRequest

CONTROL_COLUMNS = ["id", "platform", "status", "created_at", "done_at"]
_HEARTBEAT_CELL = "G1"
_TS = "%Y-%m-%d %H:%M:%S"


def request_to_row(row_id, platform: str, now: str) -> list:
    return [row_id, platform, REQ_PENDING, now, ""]


def is_stale(last_seen: str, now: _dt.datetime, threshold_seconds: int) -> bool:
    if not last_seen.strip():
        return True
    seen = _dt.datetime.strptime(last_seen.strip(), _TS)
    return (now - seen).total_seconds() > threshold_seconds


class ControlRepo:
    def __init__(self, worksheet):
        self._ws = worksheet

    def _ensure_header(self) -> None:
        if self._ws.row_values(1)[:5] != CONTROL_COLUMNS:
            self._ws.update("A1", [CONTROL_COLUMNS])

    def touch(self) -> None:
        self._ws.update(_HEARTBEAT_CELL, [[_dt.datetime.now().strftime(_TS)]])

    def last_seen(self) -> str:
        val = self._ws.acell(_HEARTBEAT_CELL).value
        return val or ""

    def add_request(self, platform: str) -> None:
        self._ensure_header()
        row_id = max(len(self._ws.col_values(1)) - 1, 0) + 1
        now = _dt.datetime.now().strftime(_TS)
        self._ws.append_row(request_to_row(row_id, platform, now),
                            value_input_option="USER_ENTERED")

    def pending_requests(self) -> list:
        rows = self._ws.get_all_values()[1:]
        out = []
        for r in rows:
            if len(r) >= 3 and r[2] == REQ_PENDING:
                out.append(SearchRequest(id=r[0], platform=r[1], status=r[2]))
        return out

    def mark(self, request_id: str, status: str) -> None:
        col_id = 1
        ids = self._ws.col_values(col_id)
        for i, val in enumerate(ids[1:], start=2):  # skip header
            if val == request_id:
                self._ws.update_cell(i, CONTROL_COLUMNS.index("status") + 1, status)
                if status == REQ_DONE:
                    self._ws.update_cell(
                        i, CONTROL_COLUMNS.index("done_at") + 1,
                        _dt.datetime.now().strftime(_TS))
                return
```

- [ ] **Step 4: Run test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_control_repo.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add sender/app/infrastructure/control_repo.py sender/tests/test_control_repo.py
git commit -m "feat: control repo with heartbeat staleness + request mapping"
```

---

### Task 9: run_search application (orchestrate one request)

**Files:**
- Create: `sender/app/application/run_search.py`
- Test: `sender/tests/test_run_search.py`

- [ ] **Step 1: Write the failing test**

```python
# sender/tests/test_run_search.py
from app.application.run_search import run_search
from app.domain.candidate import Candidate


def _cand(url, platform="linkedin"):
    return Candidate(platform=platform, kind="job", url=url, title="t", company="c",
                     salary="", location="x", summary="s")


class _FakeSearcher:
    def __init__(self, candidates, boom=False):
        self._c = candidates
        self._boom = boom
        self.started = self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def search(self, keywords_list, location, limit):
        if self._boom:
            raise RuntimeError("selector drift")
        return self._c


class _FakeRepo:
    def __init__(self):
        self.added = []

    def add_new(self, candidates):
        items = list(candidates)
        self.added += items
        return len(items)


def test_run_search_adds_found_candidates():
    repo = _FakeRepo()
    searchers = {"linkedin": _FakeSearcher([_cand("https://x/1"), _cand("https://x/2")])}
    added = run_search(["linkedin"], searchers, repo,
                       keywords=["junior"], location="Worldwide", limit=15)
    assert added == 2 and len(repo.added) == 2
    assert searchers["linkedin"].started and searchers["linkedin"].stopped


def test_run_search_survives_one_platform_failing():
    repo = _FakeRepo()
    searchers = {
        "linkedin": _FakeSearcher([], boom=True),
        "wellfound": _FakeSearcher([_cand("https://w/1", "wellfound")]),
    }
    added = run_search(["linkedin", "wellfound"], searchers, repo,
                       keywords=["junior"], location="Worldwide", limit=15)
    assert added == 1               # wellfound still ran
    assert searchers["wellfound"].stopped
    assert searchers["linkedin"].stopped   # stop() always called
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_run_search.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.application.run_search'`

- [ ] **Step 3: Write minimal implementation**

```python
# sender/app/application/run_search.py
"""Run one search request: scrape each platform, dedup-append candidates.

One platform failing neither stops the others nor kills the caller's loop.
Returns the number of new candidates written.
"""


def run_search(platforms, searchers, candidates_repo, keywords, location, limit,
               on_error=None) -> int:
    added = 0
    for platform in platforms:
        searcher = searchers[platform]
        try:
            searcher.start()
            found = searcher.search(keywords, location, limit)
            added += candidates_repo.add_new(found)
        except Exception as exc:  # noqa: BLE001 — isolate per-platform failures
            if on_error is not None:
                on_error(platform, exc)
        finally:
            try:
                searcher.stop()
            except Exception:  # noqa: BLE001
                pass
    return added
```

- [ ] **Step 4: Run test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_run_search.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add sender/app/application/run_search.py sender/tests/test_run_search.py
git commit -m "feat: run_search orchestration with per-platform isolation"
```

---

### Task 10: Worker tick + CLI `worker` subcommand

**Files:**
- Create: `sender/app/application/worker_tick.py`
- Modify: `sender/app/interface/cli.py` (add `run_worker()`)
- Modify: `sender/run.py` (dispatch `worker` arg)
- Test: `sender/tests/test_worker_tick.py`

The infinite loop is untestable; extract a pure `worker_tick` that does ONE
iteration (heartbeat, drain pending requests via a provided `run_one`) and test
that. The CLI `worker` command wires real repos and sleeps between ticks.

- [ ] **Step 1: Write the failing test**

```python
# sender/tests/test_worker_tick.py
from app.application.worker_tick import worker_tick
from app.domain.search_request import SearchRequest, REQ_DONE


class _FakeControl:
    def __init__(self, pending):
        self._pending = pending
        self.touched = False
        self.marked = []

    def touch(self):
        self.touched = True

    def pending_requests(self):
        return self._pending

    def mark(self, request_id, status):
        self.marked.append((request_id, status))


def test_worker_tick_heartbeats_and_processes_requests():
    control = _FakeControl([SearchRequest(id="1", platform="all", status="pending")])
    calls = []

    def run_one(req):
        calls.append(req.id)
        return 3

    worker_tick(control, run_one)
    assert control.touched
    assert calls == ["1"]
    assert ("1", "running") in control.marked
    assert ("1", REQ_DONE) in control.marked


def test_worker_tick_no_requests_still_heartbeats():
    control = _FakeControl([])
    worker_tick(control, lambda req: 0)
    assert control.touched
    assert control.marked == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_worker_tick.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.application.worker_tick'`

- [ ] **Step 3: Write minimal implementation**

```python
# sender/app/application/worker_tick.py
"""One iteration of the worker loop: heartbeat, then drain pending requests."""
from app.domain.search_request import REQ_RUNNING, REQ_DONE, REQ_ERROR


def worker_tick(control_repo, run_one) -> None:
    control_repo.touch()
    for req in control_repo.pending_requests():
        control_repo.mark(req.id, REQ_RUNNING)
        try:
            run_one(req)
            control_repo.mark(req.id, REQ_DONE)
        except Exception:  # noqa: BLE001 — a request never kills the loop
            control_repo.mark(req.id, REQ_ERROR)
```

Then add the `worker` wiring at the end of `sender/app/interface/cli.py`. Append:

```python
def run_worker():
    """Always-on loop: poll «Команды», scrape, write «Кандидаты». Ctrl+C to stop."""
    import time

    import gspread
    from google.oauth2.service_account import Credentials

    from app import config
    from app.application.run_search import run_search
    from app.application.worker_tick import worker_tick
    from app.domain.search_request import platforms_for
    from app.infrastructure.candidates_repo import CandidatesRepo
    from app.infrastructure.control_repo import ControlRepo
    from app.infrastructure.search.registry import build_searcher

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(config.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=scopes)
    book = gspread.authorize(creds).open_by_key(config.SHEET_ID)
    main_ws = book.worksheet(config.SHEET_TAB)
    cand_ws = book.worksheet(config.CANDIDATES_TAB)
    ctrl_ws = book.worksheet(config.CONTROL_TAB)

    control = ControlRepo(ctrl_ws)
    candidates = CandidatesRepo(cand_ws, main_ws, config.SEARCH_LIMIT_PER_PLATFORM)
    searchers = {p: build_searcher(p) for p in ("linkedin", "wellfound")}

    def run_one(req):
        return run_search(
            platforms_for(req.platform), searchers, candidates,
            keywords=config.SEARCH_KEYWORDS, location=config.SEARCH_LOCATION,
            limit=config.SEARCH_LIMIT_PER_PLATFORM,
            on_error=lambda p, e: print(f"⚠️ {p}: {e}"),
        )

    print("worker started; polling every", config.WORKER_POLL_SECONDS, "s")
    while True:
        try:
            worker_tick(control, run_one)
        except Exception as exc:  # noqa: BLE001 — survive transient sheet errors
            print("tick error:", exc)
        time.sleep(config.WORKER_POLL_SECONDS)
```

`run_worker()` lives in `cli.py` (above). The real entrypoint is `sender/run.py`
(it calls `cli.run()`), so add the dispatch THERE. The current `sender/run.py` is:

```python
from app.interface.cli import run  # noqa: E402

if __name__ == "__main__":
    run()
```

Change it to:

```python
from app.interface.cli import run, run_worker  # noqa: E402

if __name__ == "__main__":
    if sys.argv[1:2] == ["worker"]:
        run_worker()
    else:
        run()
```

(`sys` is already imported at the top of `run.py`.) The worker is then launched
with: `sender/.venv/Scripts/python.exe sender/run.py worker`.

- [ ] **Step 4: Run test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_worker_tick.py -v`
Expected: PASS (2 passed)

Also verify the CLI still imports:
Run: `sender/.venv/Scripts/python.exe -c "import app.interface.cli"`
Expected: no error.

- [ ] **Step 5: Commit**

```bash
git add sender/app/application/worker_tick.py sender/app/interface/cli.py sender/run.py sender/tests/test_worker_tick.py
git commit -m "feat: worker tick + 'run.py worker' loop"
```

---

### Task 11: LinkedIn apply branch (jobs → Easy Apply, profiles → DM)

**Files:**
- Modify: `sender/app/infrastructure/channels/linkedin.py`
- Test: `sender/tests/test_linkedin_channel.py` (extend existing)

- [ ] **Step 1: Write the failing test**

Append to `sender/tests/test_linkedin_channel.py`:

```python
from app.infrastructure.channels.linkedin import easy_apply_via_page, LinkedInChannel
from app.domain.channel import OutreachContent


class _FakeLocator:
    def __init__(self, count=1):
        self._count = count
        self.clicked = False
        self.filled = None
        self.first = self

    def count(self):
        return self._count

    def click(self):
        self.clicked = True

    def fill(self, text):
        self.filled = text


class _FakeApplyPage:
    def __init__(self):
        self.goto_url = None
        self._apply = _FakeLocator()
        self._note = _FakeLocator()
        self._submit = _FakeLocator()

    def goto(self, url, wait_until=None):
        self.goto_url = url

    def get_by_role(self, role, name=None):
        if name == "Easy Apply":
            return self._apply
        if name and "Submit" in name:
            return self._submit
        return _FakeLocator(count=0)

    def get_by_label(self, label):
        return self._note


def test_easy_apply_fills_and_submits():
    page = _FakeApplyPage()
    easy_apply_via_page(page, "https://www.linkedin.com/jobs/view/9",
                        OutreachContent(body="hi"))
    assert page.goto_url == "https://www.linkedin.com/jobs/view/9"
    assert page._apply.clicked and page._submit.clicked


def test_send_routes_job_url_to_easy_apply(monkeypatch):
    called = {}
    monkeypatch.setattr("app.infrastructure.channels.linkedin.easy_apply_via_page",
                        lambda page, url, content: called.setdefault("easy", url))
    monkeypatch.setattr("app.infrastructure.channels.linkedin.fill_and_send",
                        lambda page, url, content: called.setdefault("dm", url))
    ch = LinkedInChannel("state.json")
    ch._page = object()
    ch.send("https://www.linkedin.com/jobs/view/9", OutreachContent(body="hi"))
    assert called == {"easy": "https://www.linkedin.com/jobs/view/9"}


def test_send_routes_profile_url_to_dm(monkeypatch):
    called = {}
    monkeypatch.setattr("app.infrastructure.channels.linkedin.easy_apply_via_page",
                        lambda page, url, content: called.setdefault("easy", url))
    monkeypatch.setattr("app.infrastructure.channels.linkedin.fill_and_send",
                        lambda page, url, content: called.setdefault("dm", url))
    ch = LinkedInChannel("state.json")
    ch._page = object()
    ch.send("https://www.linkedin.com/in/jane", OutreachContent(body="hi"))
    assert called == {"dm": "https://www.linkedin.com/in/jane"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_linkedin_channel.py -v`
Expected: FAIL with `ImportError: cannot import name 'easy_apply_via_page'`

- [ ] **Step 3: Write minimal implementation**

In `sender/app/infrastructure/channels/linkedin.py`, add the import and function,
and rewrite `send`:

```python
# at top, alongside existing imports:
from app.domain.candidate import linkedin_action_for_url
```

```python
def easy_apply_via_page(page, job_url: str, content: OutreachContent) -> None:
    """Open a job and submit an Easy Apply note. `page` is a Playwright Page (or fake)."""
    page.goto(job_url, wait_until="domcontentloaded")
    apply_btn = page.get_by_role("button", name="Easy Apply")
    if apply_btn.count() == 0:
        raise ChannelError(f"no Easy Apply button on {job_url}")
    apply_btn.first.click()
    page.get_by_label("Additional questions").fill(content.body)
    page.get_by_role("button", name="Submit application").first.click()
```

Replace the existing `send` method body with:

```python
    def send(self, target: str, content: OutreachContent) -> None:
        if self._page is None:
            raise ChannelError("LinkedInChannel.start() not called")
        target = target.strip()
        if linkedin_action_for_url(target) == "easy_apply":
            easy_apply_via_page(self._page, target, content)
        else:
            fill_and_send(self._page, target, content)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_linkedin_channel.py -v`
Expected: PASS (existing tests + 3 new pass)

- [ ] **Step 5: Commit**

```bash
git add sender/app/infrastructure/channels/linkedin.py sender/tests/test_linkedin_channel.py
git commit -m "feat: LinkedIn channel routes job URLs to Easy Apply, profiles to DM"
```

---

### Task 12: Intake webhook — candidate promotion + control repos

**Files:**
- Create: `intake-bot/app/infrastructure/candidates_gateway.py`
- Test: `intake-bot/tests/test_candidates_gateway.py`

This is the intake (Vercel) side's pure logic: build the inline-keyboard message
for a candidate, parse callback data, and build the main-tab lead row when a
candidate is approved. gspread I/O is a thin shell composed from these.

- [ ] **Step 1: Write the failing test**

```python
# intake-bot/tests/test_candidates_gateway.py
from app.infrastructure.candidates_gateway import (
    build_vacancy_message, parse_callback, candidate_row_to_lead_row,
    CANDIDATE_COLUMNS,
)


def _row(id="3", platform="linkedin", kind="job",
         url="https://x/1", title="Junior Dev", company="Acme",
         salary="", location="Remote", summary="Python", status="pending",
         date="2026-06-15"):
    return [id, platform, kind, url, title, company, salary, location, summary, status, date]


def test_parse_callback():
    assert parse_callback("approve:3") == ("approve", "3")
    assert parse_callback("skip:12") == ("skip", "12")


def test_build_vacancy_message_text_and_buttons():
    text, buttons = build_vacancy_message(_row())
    assert "LinkedIn" in text and "Junior Dev" in text and "Acme" in text
    assert "Remote" in text
    # buttons: list of {text, callback_data}
    cbs = {b["callback_data"] for row in buttons for b in row}
    assert cbs == {"approve:3", "skip:3"}


def test_build_vacancy_message_blank_salary_shows_dash():
    text, _ = build_vacancy_message(_row(salary=""))
    assert "—" in text


def test_candidate_row_to_lead_row_maps_main_columns():
    from app.domain.lead import COLUMNS
    row = candidate_row_to_lead_row(_row(), row_id=5, now="2026-06-15 10:00")
    d = dict(zip(COLUMNS, row))
    assert d["id"] == 5
    assert d["Платформа"] == "linkedin"
    assert d["Цель"] == "https://x/1"
    assert "Junior Dev" in d["Вакансия"]
    assert d["Статус"] == "new"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest intake-bot/tests/test_candidates_gateway.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.infrastructure.candidates_gateway'`

- [ ] **Step 3: Write minimal implementation**

```python
# intake-bot/app/infrastructure/candidates_gateway.py
"""Intake-side view of the «Кандидаты» tab: render, parse taps, promote to main.

Pure helpers (message/buttons, callback parsing, row mapping) are unit-tested;
the CandidatesGateway class composes them over gspread worksheets.
"""
from app.domain.lead import COLUMNS, STATUS_NEW

CANDIDATE_COLUMNS = [
    "id", "Платформа", "Тип", "URL", "Title", "Company",
    "Salary", "Location", "Summary", "Статус", "Дата",
]

_BADGE = {"linkedin": "🔵 LinkedIn", "wellfound": "🅰️ Wellfound"}


def _col(row, name):
    return row[CANDIDATE_COLUMNS.index(name)]


def parse_callback(data: str):
    action, _, cid = data.partition(":")
    return action, cid


def build_vacancy_message(row):
    platform = _col(row, "Платформа")
    kind = _col(row, "Тип")
    badge = _BADGE.get(platform, platform)
    title = _col(row, "Title")
    company = _col(row, "Company")
    salary = _col(row, "Salary") or "—"
    location = _col(row, "Location") or "—"
    summary = _col(row, "Summary")
    cid = _col(row, "id")
    text = (
        f"{badge} · {kind}\n"
        f"{title} — {company}\n"
        f"💰 {salary} · 📍 {location}\n"
        f"📝 {summary}\n{_col(row, 'URL')}"
    )
    buttons = [[
        {"text": "✅ Approve", "callback_data": f"approve:{cid}"},
        {"text": "❌ Not", "callback_data": f"skip:{cid}"},
    ]]
    return text, buttons


def candidate_row_to_lead_row(row, row_id, now: str) -> list:
    """Map a «Кандидаты» row to a positional main-tab lead row (status=new)."""
    title = _col(row, "Title")
    summary = _col(row, "Summary")
    vacancy = f"{title} — {summary}".strip(" —")
    values = {
        "id": row_id,
        "Дата добавления": now,
        "Исходный текст": vacancy,
        "Платформа": _col(row, "Платформа"),
        "Цель": _col(row, "URL"),
        "Вакансия": vacancy,
        "Сообщение": "",
        "Статус": STATUS_NEW,
        "Дата отправки": "",
        "Заметка": "",
    }
    return [values[c] for c in COLUMNS]


class CandidatesGateway:
    def __init__(self, candidates_ws, main_ws):
        self._cand = candidates_ws
        self._main = main_ws

    def pending(self, limit: int):
        rows = self._cand.get_all_values()[1:]
        return [r for r in rows if len(r) >= 10 and _col(r, "Статус") == "pending"][:limit]

    def _find_row_index(self, cid: str):
        ids = self._cand.col_values(1)
        for i, val in enumerate(ids[1:], start=2):
            if val == cid:
                return i
        return None

    def _get_row(self, cid: str):
        idx = self._find_row_index(cid)
        return (idx, self._cand.row_values(idx)) if idx else (None, None)

    def approve(self, cid: str) -> bool:
        idx, row = self._get_row(cid)
        if idx is None or _col(row, "Статус") != "pending":
            return False  # idempotent: already handled / missing
        import datetime as _dt
        row_id = max(len(self._main.col_values(1)) - 1, 0) + 1
        now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        self._main.append_row(candidate_row_to_lead_row(row, row_id, now),
                              value_input_option="USER_ENTERED")
        self._cand.update_cell(idx, CANDIDATE_COLUMNS.index("Статус") + 1, "taken")
        return True

    def reject(self, cid: str) -> bool:
        idx, row = self._get_row(cid)
        if idx is None or _col(row, "Статус") != "pending":
            return False
        self._cand.update_cell(idx, CANDIDATE_COLUMNS.index("Статус") + 1, "rejected")
        return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest intake-bot/tests/test_candidates_gateway.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add intake-bot/app/infrastructure/candidates_gateway.py intake-bot/tests/test_candidates_gateway.py
git commit -m "feat: intake candidates gateway (render/promote/reject)"
```

---

### Task 13: Intake webhook — control gateway (search requests + heartbeat read)

**Files:**
- Create: `intake-bot/app/infrastructure/control_gateway.py`
- Test: `intake-bot/tests/test_control_gateway.py`

- [ ] **Step 1: Write the failing test**

```python
# intake-bot/tests/test_control_gateway.py
import datetime as _dt

from app.infrastructure.control_gateway import is_stale, start_search_reply


def test_is_stale_blank_true():
    assert is_stale("", _dt.datetime(2026, 6, 15, 10, 0, 0), 180)


def test_is_stale_fresh_false():
    now = _dt.datetime(2026, 6, 15, 10, 0, 0)
    assert not is_stale("2026-06-15 09:59:00", now, 180)


def test_start_search_reply_online():
    msg = start_search_reply(online=True)
    assert "запус" in msg.lower()


def test_start_search_reply_offline_mentions_queue():
    msg = start_search_reply(online=False)
    assert "офлайн" in msg.lower() and "очеред" in msg.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest intake-bot/tests/test_control_gateway.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.infrastructure.control_gateway'`

- [ ] **Step 3: Write minimal implementation**

```python
# intake-bot/app/infrastructure/control_gateway.py
"""Intake-side view of the «Команды» tab: queue search requests, read heartbeat."""
import datetime as _dt

CONTROL_COLUMNS = ["id", "platform", "status", "created_at", "done_at"]
_HEARTBEAT_CELL = "G1"
_TS = "%Y-%m-%d %H:%M:%S"


def is_stale(last_seen: str, now: _dt.datetime, threshold_seconds: int) -> bool:
    if not last_seen.strip():
        return True
    seen = _dt.datetime.strptime(last_seen.strip(), _TS)
    return (now - seen).total_seconds() > threshold_seconds


def start_search_reply(online: bool) -> str:
    if online:
        return "🔎 Запускаю поиск — кандидаты появятся через пару минут. Потом жми /show_vacancies."
    return ("⚠️ Ноут сейчас офлайн. Поставил поиск в очередь — выполню, как включишь ноут. "
            "Потом жми /show_vacancies.")


class ControlGateway:
    def __init__(self, control_ws):
        self._ws = control_ws

    def last_seen(self) -> str:
        return self._ws.acell(_HEARTBEAT_CELL).value or ""

    def is_worker_online(self, threshold_seconds: int) -> bool:
        return not is_stale(self.last_seen(), _dt.datetime.now(), threshold_seconds)

    def queue_search(self, platform: str = "all") -> None:
        if self._ws.row_values(1)[:5] != CONTROL_COLUMNS:
            self._ws.update("A1", [CONTROL_COLUMNS])
        row_id = max(len(self._ws.col_values(1)) - 1, 0) + 1
        now = _dt.datetime.now().strftime(_TS)
        self._ws.append_row([row_id, platform, "pending", now, ""],
                            value_input_option="USER_ENTERED")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest intake-bot/tests/test_control_gateway.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add intake-bot/app/infrastructure/control_gateway.py intake-bot/tests/test_control_gateway.py
git commit -m "feat: intake control gateway (queue search + heartbeat read)"
```

---

### Task 14: Wire `/start_search`, `/show_vacancies`, and button taps into the webhook

**Files:**
- Modify: `intake-bot/app/config.py` (add CANDIDATES_TAB, CONTROL_TAB, HEARTBEAT_STALE_SECONDS, SHOW_BATCH)
- Modify: `intake-bot/api/webhook.py`
- Test: `intake-bot/tests/test_webhook_search.py`

- [ ] **Step 1: Write the failing test**

```python
# intake-bot/tests/test_webhook_search.py
import api.webhook as wh


def test_build_search_callbacks_exist():
    # The webhook exposes pure helpers used by the handlers.
    assert hasattr(wh, "_handle_callback")
    assert hasattr(wh, "_handle_command")


def test_handle_command_dispatch(monkeypatch):
    seen = {}
    monkeypatch.setattr(wh, "_do_start_search", lambda chat_id: seen.setdefault("start", chat_id))
    monkeypatch.setattr(wh, "_do_show_vacancies", lambda chat_id: seen.setdefault("show", chat_id))
    assert wh._handle_command("/start_search", 7) is True
    assert wh._handle_command("/show_vacancies", 7) is True
    assert wh._handle_command("/not_a_cmd", 7) is False
    assert seen == {"start": 7, "show": 7}


def test_handle_callback_routes(monkeypatch):
    actions = []
    monkeypatch.setattr(wh, "_do_approve", lambda cid: actions.append(("a", cid)))
    monkeypatch.setattr(wh, "_do_skip", lambda cid: actions.append(("s", cid)))
    wh._handle_callback("approve:5")
    wh._handle_callback("skip:9")
    assert actions == [("a", "5"), ("s", "9")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest intake-bot/tests/test_webhook_search.py -v`
Expected: FAIL with `AttributeError: module 'api.webhook' has no attribute '_handle_callback'`

- [ ] **Step 3: Write minimal implementation**

First append to `intake-bot/app/config.py`:

```python
CANDIDATES_TAB = os.environ.get("CANDIDATES_TAB", "Кандидаты")
CONTROL_TAB = os.environ.get("CONTROL_TAB", "Команды")
HEARTBEAT_STALE_SECONDS = int(os.environ.get("HEARTBEAT_STALE_SECONDS", "180"))
SHOW_BATCH = int(os.environ.get("SHOW_BATCH", "7"))
```

Then in `intake-bot/api/webhook.py`, add gateway builders, command/callback
handlers, and dispatch them from `telegram_webhook`. Add near the other imports:

```python
from app.infrastructure.candidates_gateway import (  # noqa: E402
    CandidatesGateway, build_vacancy_message, parse_callback,
)
from app.infrastructure.control_gateway import ControlGateway  # noqa: E402
```

Add helper builders and handlers (after `_build_use_case`):

```python
def _book():
    import gspread
    from google.oauth2.service_account import Credentials
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    if config.GOOGLE_SERVICE_ACCOUNT_JSON.strip():
        import json
        creds = Credentials.from_service_account_info(
            json.loads(config.GOOGLE_SERVICE_ACCOUNT_JSON), scopes=scopes)
    else:
        creds = Credentials.from_service_account_file(
            config.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=scopes)
    return gspread.authorize(creds).open_by_key(config.SHEET_ID)


def _candidates_gateway():
    book = _book()
    return CandidatesGateway(book.worksheet(config.CANDIDATES_TAB),
                             book.worksheet(config.SHEET_TAB))


def _control_gateway():
    return ControlGateway(_book().worksheet(config.CONTROL_TAB))


def _reply_with_buttons(chat_id: int, text: str, buttons) -> None:
    import json
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": text,
               "reply_markup": json.dumps({"inline_keyboard": buttons})}
    data = urllib.parse.urlencode(payload).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10)
    except Exception:
        pass


def _do_start_search(chat_id: int) -> None:
    from app.infrastructure.control_gateway import start_search_reply
    ctrl = _control_gateway()
    online = ctrl.is_worker_online(config.HEARTBEAT_STALE_SECONDS)
    ctrl.queue_search("all")           # warn + queue regardless
    _reply(chat_id, start_search_reply(online))


def _do_show_vacancies(chat_id: int) -> None:
    gw = _candidates_gateway()
    rows = gw.pending(config.SHOW_BATCH)
    if not rows:
        _reply(chat_id, "Пока нет новых вакансий. Запусти /start_search.")
        return
    for row in rows:
        text, buttons = build_vacancy_message(row)
        _reply_with_buttons(chat_id, text, buttons)


def _do_approve(cid: str) -> None:
    _candidates_gateway().approve(cid)


def _do_skip(cid: str) -> None:
    _candidates_gateway().reject(cid)


def _handle_command(text: str, chat_id: int) -> bool:
    if text.startswith("/start_search"):
        _do_start_search(chat_id)
        return True
    if text.startswith("/show_vacancies"):
        _do_show_vacancies(chat_id)
        return True
    return False


def _handle_callback(data: str) -> None:
    action, cid = parse_callback(data)
    if action == "approve":
        _do_approve(cid)
    elif action == "skip":
        _do_skip(cid)
```

Finally, in `telegram_webhook`, handle callback queries and the new commands.
Right after `update = await request.json()` add:

```python
    callback = update.get("callback_query")
    if callback:
        data = callback.get("data", "")
        _handle_callback(data)
        cb_msg = callback.get("message") or {}
        cb_chat = (cb_msg.get("chat") or {}).get("id")
        if cb_chat:
            verdict = "✅ Взято" if data.startswith("approve") else "❌ Скип"
            _reply(cb_chat, verdict)
        return {"ok": True}
```

And after the `/status` block (before the `try: lead = ...`) add:

```python
    if _handle_command(text, chat_id):
        return {"ok": True}
```

Also extend the `/start` help text to mention `/start_search` and `/show_vacancies`.

- [ ] **Step 4: Run test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest intake-bot/tests/test_webhook_search.py -v`
Expected: PASS (3 passed)

Verify the module imports:
Run: `sender/.venv/Scripts/python.exe -c "import sys; sys.path.insert(0,'intake-bot'); import api.webhook"`
Expected: no error.

- [ ] **Step 5: Commit**

```bash
git add intake-bot/app/config.py intake-bot/api/webhook.py intake-bot/tests/test_webhook_search.py
git commit -m "feat: wire /start_search, /show_vacancies, approve/skip into webhook"
```

---

### Task 15: Full suite + README + Apps Script tab notes

**Files:**
- Modify: `README.md`
- Test: full suites

- [ ] **Step 1: Run the full sender + intake suites**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests intake-bot/tests -q`
Expected: PASS (all green). Fix any regression before continuing.

- [ ] **Step 2: Document the feature in README.md**

Add a "Vacancy search (sub-project C)" section covering: create two sheet tabs
named «Кандидаты» and «Команды»; run `sender/.venv/Scripts/python.exe sender/run.py worker` on the laptop (first
run opens browsers to log into LinkedIn/Wellfound once, sessions saved to the
gitignored `*_state.json`); from Telegram use `/start_search` to scrape and
`/show_vacancies` to review 7 at a time with ✅/❌; approved candidates land in the
main tab as `new` and the existing sender (`sender/run.py`) applies to them.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document vacancy search worker + Telegram review flow"
```

---

## Notes for the implementer

- **Selectors are guesses.** The `_job_cards`/`_people_cards`/`_job_cards`
  (Wellfound) selector strings in Tasks 4–5 WILL need adjustment against the live
  sites; that is expected and isolated. The pure `parse_*`, URL builders, dedup,
  cap, heartbeat, mapping, and handler-routing logic are what the tests lock down.
- **Two sheet tabs must exist** before the worker/webhook run: «Кандидаты» and
  «Команды». The repos write their headers on first use, but the tabs themselves
  must be created in the spreadsheet UI (or via Apps Script).
- **Heartbeat cell** is `G1` of the «Команды» tab on both sides — keep them in
  sync if you move it.
- The intake bot has **no venv**; always run its tests with the sender venv
  interpreter as shown.
```
