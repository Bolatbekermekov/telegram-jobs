# RemoteOK + We Work Remotely Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two HTTP-only job-search platforms — RemoteOK and We Work Remotely — to the existing search pipeline, fully integrated like LinkedIn/Wellfound.

**Architecture:** Each platform is a new `Searcher` implementing the same interface as `LinkedInSearcher` (`name`, `start`, `stop`, `search`, `describe`), but over plain HTTP (no browser, no login). Raw JSON/HTML parsing is isolated in pure, unit-tested functions; network I/O is a thin wrapper. The new searchers are picked up "for free" by `run_search` (dedup → AI scoring → write to «Кандидаты»); no changes to `run_search` are needed.

**Tech Stack:** Python 3, `httpx` (already a dependency) for HTTP, `beautifulsoup4` (new) for WWR HTML parsing, pytest.

## Global Constraints

- Platform keys: RemoteOK = `"remoteok"`, We Work Remotely = `"wwr"`. Use these exact strings everywhere (registry, SEARCH_PLATFORMS, command tokens, badges).
- New searchers must NOT launch a browser or require login. `start()`/`stop()` are no-ops.
- HTTP only via `httpx`; all requests pass a `User-Agent` header and an explicit timeout.
- Candidate fields use `app.domain.candidate.Candidate` with `kind=KIND_JOB`. `summary` is left `""` (the AI scorer overwrites it with `"<score>/100: <reason>"`).
- Dedup-before-scoring is already handled by `run_search` (`candidates_repo.known_urls()` filters before `describe()`+scoring). `describe()` must NOT make a network call for RemoteOK (description is cached from the list fetch); for WWR `describe()` fetches the job page, but only for already-deduped URLs.
- Sender tests run with `sender/.venv/Scripts/python.exe`; run them from the `sender/` directory. Intake tests run with the same interpreter but from the `intake-bot/` directory (run the two suites SEPARATELY — combining causes ImportPathMismatchError).
- AI threshold stays 60 (`MATCH_THRESHOLD`), keywords stay `SEARCH_KEYWORDS`, per-platform budget stays `SEARCH_LIMIT_PER_PLATFORM` — no new config for these.

---

## File Structure

**New files:**
- `sender/app/infrastructure/search/remoteok_search.py` — RemoteOK pure parsers + `RemoteOKSearcher`.
- `sender/app/infrastructure/search/wwr_search.py` — WWR pure parsers + `WWRSearcher`.
- `sender/tests/test_remoteok_search.py` — RemoteOK parser/searcher tests.
- `sender/tests/test_wwr_search.py` — WWR parser tests.
- `sender/tests/test_bot_menu_platforms.py` — bot menu includes new commands.
- `sender/tests/test_search_platforms.py` — `SEARCH_PLATFORMS` includes new platforms.
- `intake-bot/tests/test_new_platforms.py` — intake command mapping + badges.

**Modified files:**
- `sender/app/infrastructure/search/registry.py` — two new `build_searcher` cases.
- `sender/app/domain/search_request.py` — extend `SEARCH_PLATFORMS`.
- `sender/app/application/search_commands.py` — two new tokens.
- `sender/run.py` — dispatch two new tokens.
- `sender/register_bot_menu.py` — two new menu commands.
- `sender/app/config.py` — HTTP settings (UA, URLs, timeout).
- `sender/app/domain/candidate.py` — update `platform` comment.
- `sender/requirements.txt` — add `beautifulsoup4`.
- `sender/tests/test_search_commands.py` — assert new tokens.
- `sender/tests/test_search_registry.py` — build new searchers.
- `intake-bot/app/domain/bot_commands.py` — map new commands.
- `intake-bot/app/infrastructure/candidates_gateway.py` — badges for new platforms.
- `intake-bot/api/webhook.py` — mention new commands in /start help.
- `Makefile` — `search_remoteok`, `search_wwr` targets + help + .PHONY.

---

## Task 1: RemoteOK searcher

**Files:**
- Create: `sender/app/infrastructure/search/remoteok_search.py`
- Test: `sender/tests/test_remoteok_search.py`

**Interfaces:**
- Consumes: `app.domain.candidate.Candidate`, `KIND_JOB`, `normalize_url`.
- Produces:
  - `parse_remoteok_jobs(payload: list) -> list[dict]`
  - `job_matches(job: dict, keywords: list[str]) -> bool`
  - `format_salary(lo, hi) -> str`
  - `strip_html(text: str) -> str`
  - `to_candidate(job: dict) -> Candidate`
  - `class RemoteOKSearcher` with `name = "remoteok"`, `start()`, `stop()`, `search(keywords_list, location, limit) -> list[Candidate]`, `describe(url) -> str`.

- [ ] **Step 1: Write the failing test**

Create `sender/tests/test_remoteok_search.py`:

```python
from app.domain.candidate import KIND_JOB
from app.infrastructure.search.remoteok_search import (
    RemoteOKSearcher, format_salary, job_matches, parse_remoteok_jobs,
    strip_html, to_candidate,
)

PAYLOAD = [
    {"legal": "RemoteOK disclaimer, see https://remoteok.com/api"},
    {
        "id": "1", "position": "Junior Backend Developer", "company": "Acme",
        "location": "Worldwide", "tags": ["dev", "backend", "golang"],
        "description": "<p>We use <b>Go</b> and Postgres.</p>",
        "url": "https://remoteok.com/remote-jobs/1",
        "salary_min": 50000, "salary_max": 80000,
    },
    {
        "id": "2", "position": "Senior Sales Manager", "company": "SellCo",
        "location": "US", "tags": ["sales"],
        "description": "<p>Cold calls.</p>",
        "url": "https://remoteok.com/remote-jobs/2",
        "salary_min": 0, "salary_max": 0,
    },
]


def test_parse_skips_disclaimer():
    jobs = parse_remoteok_jobs(PAYLOAD)
    assert [j["id"] for j in jobs] == ["1", "2"]


def test_job_matches_title_and_tags():
    jobs = parse_remoteok_jobs(PAYLOAD)
    assert job_matches(jobs[0], ["backend"]) is True       # in tags + title
    assert job_matches(jobs[1], ["backend"]) is False
    assert job_matches(jobs[1], ["sales"]) is True          # in tags


def test_strip_html():
    assert strip_html("<p>We use <b>Go</b> and Postgres.</p>") == "We use Go and Postgres."


def test_format_salary():
    assert format_salary(50000, 80000) == "$50,000–$80,000"
    assert format_salary(0, 0) == ""


def test_to_candidate_maps_fields():
    job = parse_remoteok_jobs(PAYLOAD)[0]
    c = to_candidate(job)
    assert c.platform == "remoteok"
    assert c.kind == KIND_JOB
    assert c.title == "Junior Backend Developer"
    assert c.company == "Acme"
    assert c.salary == "$50,000–$80,000"
    assert c.location == "Worldwide"
    assert c.url == "https://remoteok.com/remote-jobs/1"
    assert c.summary == ""   # AI scorer fills this later


def test_search_filters_and_caches_description():
    s = RemoteOKSearcher()
    s._payload = lambda: PAYLOAD                      # stub network
    found = s.search(["backend"], "Worldwide", limit=10)
    assert [c.title for c in found] == ["Junior Backend Developer"]
    # describe() returns the cached, HTML-stripped description (no network call)
    assert s.describe("https://remoteok.com/remote-jobs/1") == "We use Go and Postgres."


def test_start_stop_are_noops():
    s = RemoteOKSearcher()
    s.start()
    s.stop()  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd sender && .venv/Scripts/python.exe -m pytest tests/test_remoteok_search.py -v`
Expected: FAIL with `ModuleNotFoundError: app.infrastructure.search.remoteok_search`.

- [ ] **Step 3: Write minimal implementation**

Create `sender/app/infrastructure/search/remoteok_search.py`:

```python
"""RemoteOK searcher over the public JSON API (no browser, no login).

The API (https://remoteok.com/api) returns the latest postings as a JSON array
whose FIRST element is a legal disclaimer (no job fields). Each job already
includes its description, so describe() is served from a cache built during
search() — no second request, no extra AI cost on repeats.
"""
import re

import httpx

from app.domain.candidate import KIND_JOB, Candidate, normalize_url

REMOTEOK_API_URL = "https://remoteok.com/api"
DEFAULT_UA = "Mozilla/5.0 (compatible; telegram-jobs/1.0)"

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(text: str) -> str:
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", text or "")).strip()


def format_salary(lo, hi) -> str:
    lo = int(lo or 0)
    hi = int(hi or 0)
    if lo <= 0 and hi <= 0:
        return ""
    if lo > 0 and hi > 0:
        return f"${lo:,}–${hi:,}"
    return f"${(lo or hi):,}"


def parse_remoteok_jobs(payload: list) -> list[dict]:
    """Drop the disclaimer element; keep entries that look like jobs."""
    jobs = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        if not item.get("id") or not item.get("position"):
            continue  # disclaimer / malformed
        jobs.append({
            "id": str(item.get("id")),
            "title": item.get("position", ""),
            "company": item.get("company", ""),
            "location": item.get("location", "") or "Remote",
            "tags": [str(t) for t in (item.get("tags") or [])],
            "description": item.get("description", ""),
            "url": item.get("url", ""),
            "salary_min": item.get("salary_min", 0),
            "salary_max": item.get("salary_max", 0),
        })
    return jobs


def job_matches(job: dict, keywords: list[str]) -> bool:
    haystack = " ".join([
        job.get("title", ""), " ".join(job.get("tags", [])),
        strip_html(job.get("description", "")),
    ]).lower()
    return any(kw.lower() in haystack for kw in keywords if kw.strip())


def to_candidate(job: dict) -> Candidate:
    return Candidate(
        platform="remoteok", kind=KIND_JOB,
        url=job.get("url", ""),
        title=job.get("title", ""),
        company=job.get("company", ""),
        salary=format_salary(job.get("salary_min"), job.get("salary_max")),
        location=job.get("location", ""),
        summary="",
    )


class RemoteOKSearcher:
    name = "remoteok"

    def __init__(self, api_url: str = REMOTEOK_API_URL,
                 user_agent: str = DEFAULT_UA, timeout: int = 20):
        self._api_url = api_url
        self._ua = user_agent
        self._timeout = timeout
        self._desc: dict[str, str] = {}

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def _payload(self) -> list:
        resp = httpx.get(self._api_url, headers={"User-Agent": self._ua},
                         timeout=self._timeout, follow_redirects=True)
        resp.raise_for_status()
        return resp.json()

    def search(self, keywords_list, location, limit) -> list[Candidate]:
        jobs = parse_remoteok_jobs(self._payload())
        found: list[Candidate] = []
        for job in jobs:
            if not job_matches(job, keywords_list):
                continue
            self._desc[normalize_url(job["url"])] = strip_html(job["description"])
            found.append(to_candidate(job))
            if len(found) >= limit:
                break
        return found

    def describe(self, url: str) -> str:
        return self._desc.get(normalize_url(url), "")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd sender && .venv/Scripts/python.exe -m pytest tests/test_remoteok_search.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add sender/app/infrastructure/search/remoteok_search.py sender/tests/test_remoteok_search.py
git commit -m "feat: RemoteOK HTTP searcher (JSON API, cached describe)"
```

---

## Task 2: We Work Remotely searcher

**Files:**
- Create: `sender/app/infrastructure/search/wwr_search.py`
- Modify: `sender/requirements.txt` (add `beautifulsoup4`)
- Test: `sender/tests/test_wwr_search.py`

**Interfaces:**
- Consumes: `app.domain.candidate.Candidate`, `KIND_JOB`; `app.domain.search_request.per_keyword_limit`.
- Produces:
  - `parse_wwr_cards(html: str, base_url: str) -> list[Candidate]`
  - `parse_wwr_description(html: str) -> str`
  - `class WWRSearcher` with `name = "wwr"`, `start()`, `stop()`, `search(keywords_list, location, limit) -> list[Candidate]`, `describe(url) -> str`.

- [ ] **Step 1: Add the dependency**

Edit `sender/requirements.txt`, add a line at the end:

```
beautifulsoup4==4.12.3
```

Install it:

Run: `cd sender && .venv/Scripts/python.exe -m pip install beautifulsoup4==4.12.3`
Expected: "Successfully installed beautifulsoup4-4.12.3 ..." (or "already satisfied").

- [ ] **Step 2: Write the failing test**

Create `sender/tests/test_wwr_search.py`:

```python
from app.infrastructure.search.wwr_search import (
    parse_wwr_cards, parse_wwr_description,
)

SEARCH_HTML = """
<section class="jobs">
  <article>
    <ul>
      <li class="feature">
        <a href="/remote-jobs/acme-junior-backend-developer">
          <span class="company">Acme</span>
          <span class="title">Junior Backend Developer</span>
          <span class="region company">Anywhere (100% Remote)</span>
        </a>
      </li>
      <li class="view-all">
        <a href="/remote-full-stack-programming-jobs">View all</a>
      </li>
      <li>
        <a href="/remote-jobs/sellco-frontend-engineer">
          <span class="company">SellCo</span>
          <span class="title">Frontend Engineer</span>
          <span class="region company">USA Only</span>
        </a>
      </li>
    </ul>
  </article>
</section>
"""

JOB_HTML = """
<html><body>
  <div class="listing-container">
    <p>We build developer tools in Go and TypeScript.</p>
    <p>You will own backend services.</p>
  </div>
</body></html>
"""


def test_parse_cards_extracts_jobs_skips_view_all():
    cards = parse_wwr_cards(SEARCH_HTML, base_url="https://weworkremotely.com")
    assert len(cards) == 2
    first = cards[0]
    assert first.platform == "wwr"
    assert first.title == "Junior Backend Developer"
    assert first.company == "Acme"
    assert first.url == (
        "https://weworkremotely.com/remote-jobs/acme-junior-backend-developer")
    assert first.summary == ""


def test_parse_description():
    text = parse_wwr_description(JOB_HTML)
    assert "developer tools in Go and TypeScript" in text
    assert "own backend services" in text
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd sender && .venv/Scripts/python.exe -m pytest tests/test_wwr_search.py -v`
Expected: FAIL with `ModuleNotFoundError: app.infrastructure.search.wwr_search`.

- [ ] **Step 4: Write minimal implementation**

Create `sender/app/infrastructure/search/wwr_search.py`:

```python
"""We Work Remotely searcher over plain HTTP (no API, no login).

Uses the public search page per keyword; descriptions come from each job page.
HTML parsing (bs4) is isolated in parse_* so selector drift is easy to fix.
"""
import httpx
from bs4 import BeautifulSoup

from app.domain.candidate import KIND_JOB, Candidate
from app.domain.search_request import per_keyword_limit

WWR_BASE_URL = "https://weworkremotely.com"
DEFAULT_UA = "Mozilla/5.0 (compatible; telegram-jobs/1.0)"


def _abs_url(href: str, base_url: str) -> str:
    if href.startswith("http"):
        return href
    return f"{base_url}{href}"


def parse_wwr_cards(html: str, base_url: str = WWR_BASE_URL) -> list[Candidate]:
    soup = BeautifulSoup(html, "html.parser")
    cards: list[Candidate] = []
    for li in soup.select("section.jobs li"):
        link = li.find("a", href=True)
        title_el = li.select_one("span.title")
        if not link or not title_el:
            continue  # skips "view all" / section rows that have no job title
        company_el = li.select_one("span.company")
        region_el = li.select_one("span.region")
        cards.append(Candidate(
            platform="wwr", kind=KIND_JOB,
            url=_abs_url(link["href"], base_url),
            title=title_el.get_text(strip=True),
            company=company_el.get_text(strip=True) if company_el else "",
            salary="",
            location=region_el.get_text(strip=True) if region_el else "",
            summary="",
        ))
    return cards


def parse_wwr_description(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for sel in ["div.listing-container", "#job-listing-show-container",
                "section.listing-container", "main"]:
        el = soup.select_one(sel)
        if el:
            text = el.get_text(" ", strip=True)
            if len(text) > 50:
                return text[:6000]
    return ""


class WWRSearcher:
    name = "wwr"

    def __init__(self, base_url: str = WWR_BASE_URL,
                 user_agent: str = DEFAULT_UA, timeout: int = 20):
        self._base = base_url.rstrip("/")
        self._ua = user_agent
        self._timeout = timeout

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def _get(self, url: str) -> str:
        resp = httpx.get(url, headers={"User-Agent": self._ua},
                         timeout=self._timeout, follow_redirects=True)
        resp.raise_for_status()
        return resp.text

    def search(self, keywords_list, location, limit) -> list[Candidate]:
        per_kw = per_keyword_limit(limit, len(keywords_list))
        found: list[Candidate] = []
        for kw in keywords_list:
            url = f"{self._base}/remote-jobs/search?term={httpx.QueryParams({'q': kw})['q']}"
            try:
                html = self._get(url)
            except Exception:  # noqa: BLE001 — one keyword failing must not kill the rest
                continue
            found += parse_wwr_cards(html, self._base)[:per_kw]
        return found[:limit]

    def describe(self, url: str) -> str:
        try:
            return parse_wwr_description(self._get(url))
        except Exception:  # noqa: BLE001
            return ""
```

Note: the URL line uses `httpx.QueryParams` only to URL-encode the keyword; simpler equivalent is `urllib.parse.quote(kw)`. If you prefer, replace that line with:

```python
            from urllib.parse import quote
            url = f"{self._base}/remote-jobs/search?term={quote(kw)}"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd sender && .venv/Scripts/python.exe -m pytest tests/test_wwr_search.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Verify selectors against live HTML (manual sanity check)**

WWR markup can drift. Confirm the parsers work on the real site:

Run:
```bash
cd sender && .venv/Scripts/python.exe -c "from app.infrastructure.search.wwr_search import WWRSearcher; s=WWRSearcher(); r=s.search(['backend'],'Worldwide',3); print(len(r)); [print(c.title,'|',c.company,'|',c.url) for c in r]; print('DESC:', s.describe(r[0].url)[:200] if r else 'none')"
```
Expected: prints a non-zero count with plausible titles/companies and a non-empty DESC. If count is 0 or fields are blank, adjust the selectors in `parse_wwr_cards`/`parse_wwr_description` (inspect the live HTML) and re-run Step 5, then this step.

- [ ] **Step 7: Commit**

```bash
git add sender/app/infrastructure/search/wwr_search.py sender/tests/test_wwr_search.py sender/requirements.txt
git commit -m "feat: We Work Remotely HTTP searcher (bs4 parsing)"
```

---

## Task 3: Sender-side wiring (config, registry, commands, run, menu, Makefile)

**Files:**
- Modify: `sender/app/config.py`
- Modify: `sender/app/infrastructure/search/registry.py`
- Modify: `sender/app/domain/search_request.py`
- Modify: `sender/app/application/search_commands.py`
- Modify: `sender/run.py`
- Modify: `sender/register_bot_menu.py`
- Modify: `sender/app/domain/candidate.py`
- Modify: `Makefile`
- Modify: `sender/tests/test_search_commands.py`
- Modify: `sender/tests/test_search_registry.py`
- Create: `sender/tests/test_search_platforms.py`
- Create: `sender/tests/test_bot_menu_platforms.py`

**Interfaces:**
- Consumes: `RemoteOKSearcher`, `WWRSearcher` (Task 1, 2); `config.HTTP_USER_AGENT`, `config.REMOTEOK_API_URL`, `config.WWR_BASE_URL`, `config.HTTP_TIMEOUT_SECONDS` (added here).
- Produces: `build_searcher("remoteok")`, `build_searcher("wwr")`; `platforms_arg("search_remoteok")`, `platforms_arg("search_wwr")`; `SEARCH_PLATFORMS` containing both.

- [ ] **Step 1: Write the failing tests**

Edit `sender/tests/test_search_commands.py`, replace `test_per_platform_tokens` with:

```python
def test_per_platform_tokens():
    assert platforms_arg("search_linkedin") == ["linkedin"]
    assert platforms_arg("search_wellfound") == ["wellfound"]
    assert platforms_arg("search_remoteok") == ["remoteok"]
    assert platforms_arg("search_wwr") == ["wwr"]
```

And update `test_search_token_means_all_platforms`:

```python
def test_search_token_means_all_platforms():
    assert platforms_arg("search") == ["linkedin", "wellfound", "remoteok", "wwr"]
```

Edit `sender/tests/test_search_registry.py`, add at the end:

```python
def test_build_remoteok():
    from app.infrastructure.search.remoteok_search import RemoteOKSearcher
    assert isinstance(build_searcher("remoteok"), RemoteOKSearcher)


def test_build_wwr():
    from app.infrastructure.search.wwr_search import WWRSearcher
    assert isinstance(build_searcher("wwr"), WWRSearcher)
```

Create `sender/tests/test_search_platforms.py`:

```python
from app.domain.search_request import SEARCH_PLATFORMS, platforms_for


def test_search_platforms_includes_new_boards():
    assert "remoteok" in SEARCH_PLATFORMS
    assert "wwr" in SEARCH_PLATFORMS


def test_all_expands_to_every_platform():
    assert platforms_for("all") == ["linkedin", "wellfound", "remoteok", "wwr"]
```

Create `sender/tests/test_bot_menu_platforms.py`:

```python
from register_bot_menu import bot_commands_payload


def test_menu_has_new_search_commands():
    commands = {c["command"] for c in bot_commands_payload()}
    assert "search_remoteok" in commands
    assert "search_wwr" in commands
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd sender && .venv/Scripts/python.exe -m pytest tests/test_search_commands.py tests/test_search_registry.py tests/test_search_platforms.py tests/test_bot_menu_platforms.py -v`
Expected: FAIL (KeyError on tokens / assertion errors / missing searchers).

- [ ] **Step 3: Add config settings**

Edit `sender/app/config.py`. After the LinkedIn search block (the `LINKEDIN_POSTED_WITHIN` line, ~line 115), add:

```python
# RemoteOK / We Work Remotely (HTTP-only platforms — no browser, no login).
HTTP_USER_AGENT = os.environ.get(
    "HTTP_USER_AGENT", "Mozilla/5.0 (compatible; telegram-jobs/1.0)")
HTTP_TIMEOUT_SECONDS = int(os.environ.get("HTTP_TIMEOUT_SECONDS", "20"))
REMOTEOK_API_URL = os.environ.get("REMOTEOK_API_URL", "https://remoteok.com/api")
WWR_BASE_URL = os.environ.get("WWR_BASE_URL", "https://weworkremotely.com")
```

- [ ] **Step 4: Extend SEARCH_PLATFORMS**

Edit `sender/app/domain/search_request.py`, change:

```python
SEARCH_PLATFORMS = ["linkedin", "wellfound"]
```
to:
```python
SEARCH_PLATFORMS = ["linkedin", "wellfound", "remoteok", "wwr"]
```

- [ ] **Step 5: Add registry cases**

Edit `sender/app/infrastructure/search/registry.py`. Add imports at the top:

```python
from app.infrastructure.search.remoteok_search import RemoteOKSearcher
from app.infrastructure.search.wwr_search import WWRSearcher
```

Add before the final `raise ValueError(...)`:

```python
    if platform == "remoteok":
        return RemoteOKSearcher(
            api_url=config.REMOTEOK_API_URL,
            user_agent=config.HTTP_USER_AGENT,
            timeout=config.HTTP_TIMEOUT_SECONDS,
        )
    if platform == "wwr":
        return WWRSearcher(
            base_url=config.WWR_BASE_URL,
            user_agent=config.HTTP_USER_AGENT,
            timeout=config.HTTP_TIMEOUT_SECONDS,
        )
```

- [ ] **Step 6: Add command tokens**

Edit `sender/app/application/search_commands.py`, extend `_TOKEN_TO_PLATFORM`:

```python
_TOKEN_TO_PLATFORM = {
    "search": "all",
    "search_linkedin": "linkedin",
    "search_wellfound": "wellfound",
    "search_remoteok": "remoteok",
    "search_wwr": "wwr",
}
```

Edit `sender/run.py`, change the token tuple:

```python
    elif cmd and cmd[0] in ("search", "search_linkedin", "search_wellfound",
                            "search_remoteok", "search_wwr"):
```

- [ ] **Step 7: Add bot menu commands**

Edit `sender/register_bot_menu.py`, add to the `bot_commands_payload()` list (after the `search_wellfound` entry):

```python
        {"command": "search_remoteok", "description": "Искать вакансии в RemoteOK"},
        {"command": "search_wwr", "description": "Искать вакансии в We Work Remotely"},
```

- [ ] **Step 8: Update candidate comment**

Edit `sender/app/domain/candidate.py`, change the `Candidate.platform` comment:

```python
    platform: str    # linkedin | wellfound | remoteok | wwr
```

- [ ] **Step 9: Add Makefile targets**

Edit `Makefile`:

Add to the help block (after the `search_wellfound` help line):
```
#   make search_remoteok -> one-shot RemoteOK search
#   make search_wwr      -> one-shot We Work Remotely search
```

Add `search_remoteok search_wwr` to the `.PHONY` line.

Add targets after the `search_wellfound` target:
```makefile
search_remoteok:
	$(PYTHON) sender/run.py search_remoteok

search_wwr:
	$(PYTHON) sender/run.py search_wwr
```

- [ ] **Step 10: Run tests to verify they pass**

Run: `cd sender && .venv/Scripts/python.exe -m pytest tests/test_search_commands.py tests/test_search_registry.py tests/test_search_platforms.py tests/test_bot_menu_platforms.py -v`
Expected: PASS (all).

- [ ] **Step 11: Commit**

```bash
git add sender/app/config.py sender/app/infrastructure/search/registry.py sender/app/domain/search_request.py sender/app/application/search_commands.py sender/run.py sender/register_bot_menu.py sender/app/domain/candidate.py Makefile sender/tests/test_search_commands.py sender/tests/test_search_registry.py sender/tests/test_search_platforms.py sender/tests/test_bot_menu_platforms.py
git commit -m "feat: wire RemoteOK + WWR into sender (registry, commands, menu, Makefile)"
```

---

## Task 4: Intake-side wiring (commands, badges, help) + full verification

**Files:**
- Modify: `intake-bot/app/domain/bot_commands.py`
- Modify: `intake-bot/app/infrastructure/candidates_gateway.py`
- Modify: `intake-bot/api/webhook.py`
- Create: `intake-bot/tests/test_new_platforms.py`

**Interfaces:**
- Consumes: `command_to_search_platform` (intake), `_BADGE` / `build_vacancy_message`.
- Produces: `/search_remoteok` → `"remoteok"`, `/search_wwr` → `"wwr"`; badges for both in vacancy cards.

- [ ] **Step 1: Write the failing test**

Create `intake-bot/tests/test_new_platforms.py`:

```python
from app.domain.bot_commands import command_to_search_platform
from app.infrastructure.candidates_gateway import build_vacancy_message

CANDIDATE_COLUMNS = [
    "id", "Платформа", "Тип", "URL", "Title", "Company",
    "Salary", "Location", "Summary", "Статус", "Дата",
]


def _row(platform):
    values = {
        "id": "7", "Платформа": platform, "Тип": "job",
        "URL": "https://example.com/x", "Title": "Junior Dev", "Company": "Acme",
        "Salary": "", "Location": "Remote", "Summary": "80/100: fits",
        "Статус": "pending", "Дата": "2026-06-21 10:00",
    }
    return [values[c] for c in CANDIDATE_COLUMNS]


def test_commands_map_new_platforms():
    assert command_to_search_platform("/search_remoteok") == "remoteok"
    assert command_to_search_platform("/search_wwr") == "wwr"


def test_badges_for_new_platforms():
    remoteok_text, _ = build_vacancy_message(_row("remoteok"))
    wwr_text, _ = build_vacancy_message(_row("wwr"))
    assert "RemoteOK" in remoteok_text
    assert "WWR" in wwr_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd intake-bot && ../sender/.venv/Scripts/python.exe -m pytest tests/test_new_platforms.py -v`
Expected: FAIL (commands return None; badges fall back to raw platform key).

- [ ] **Step 3: Map the new commands**

Edit `intake-bot/app/domain/bot_commands.py`, add before the `/start_search` check:

```python
    if t.startswith("/search_remoteok"):
        return "remoteok"
    if t.startswith("/search_wwr"):
        return "wwr"
```

- [ ] **Step 4: Add badges**

Edit `intake-bot/app/infrastructure/candidates_gateway.py`, extend `_BADGE`:

```python
_BADGE = {
    "linkedin": "🔵 LinkedIn", "wellfound": "🅰️ Wellfound",
    "remoteok": "🟢 RemoteOK", "wwr": "🟧 WWR",
}
```

- [ ] **Step 5: Mention new commands in /start help**

Edit `intake-bot/api/webhook.py`, in the `/start` reply text, change the search line to:

```python
            "Поиск: /start_search — по всем платформам, /search_linkedin, "
            "/search_wellfound, /search_remoteok, /search_wwr. "
            "/show_vacancies — показать найденные.",
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd intake-bot && ../sender/.venv/Scripts/python.exe -m pytest tests/test_new_platforms.py -v`
Expected: PASS (2 tests).

- [ ] **Step 7: Run BOTH full suites**

Run: `cd sender && .venv/Scripts/python.exe -m pytest tests -q`
Expected: all pass (existing + new sender tests).

Run: `cd intake-bot && ../sender/.venv/Scripts/python.exe -m pytest tests -q`
Expected: all pass (existing + new intake tests).

- [ ] **Step 8: Live smoke test of both new searchers**

Run:
```bash
cd sender && .venv/Scripts/python.exe run.py search_remoteok
```
Expected: "Ищу вакансии: remoteok..." then "Новых кандидатов записано: N." (N may be 0 if everything is already known / nothing scores ≥60 — that's still success; no traceback).

Run:
```bash
cd sender && .venv/Scripts/python.exe run.py search_wwr
```
Expected: same shape for WWR.

If either throws a network/parse traceback, debug (systematic-debugging) before committing.

- [ ] **Step 9: Commit**

```bash
git add intake-bot/app/domain/bot_commands.py intake-bot/app/infrastructure/candidates_gateway.py intake-bot/api/webhook.py intake-bot/tests/test_new_platforms.py
git commit -m "feat: wire RemoteOK + WWR into intake bot (commands, badges, help)"
```

---

## Post-implementation (user actions, not code)

- Run `make bot_menu` once so `/search_remoteok` and `/search_wwr` appear in Telegram.
- Deploy `intake-bot` to Vercel so the new commands/badges/help reach production.
- Optional: add `HTTP_USER_AGENT` / `REMOTEOK_API_URL` / `WWR_BASE_URL` overrides to `.env` only if defaults need changing.

## Notes / risks

- **WWR selectors**: WWR ships server-rendered HTML but markup can change. Task 2 Step 6 verifies selectors against the live site; if WWR returns 0 cards in the live smoke test, the fix is localized to `parse_wwr_cards`/`parse_wwr_description`.
- **RemoteOK rate limits / UA blocking**: the API can 429 or block default UAs. We always send a browser-like `User-Agent`; on error the platform yields 0 and the others still run (existing `on_error` in `run_search`).
- **Cost**: RemoteOK `describe()` is cache-served (no network, no extra AI on repeats). WWR `describe()` fetches the job page but only for URLs that survived dedup, so repeats cost nothing.
