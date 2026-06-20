# AI-relevance Vacancy Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For each found vacancy, fetch its description, have an AI score relevance (0-100) against a user-written search profile, keep only score ≥ threshold (writing `score/100: reason` into Summary), capped at 12 jobs/platform/run, and target Intern/Junior/Junior+ remote-worldwide roles.

**Architecture:** A pure `score_and_filter` orchestration sits between `searcher.search()` and `candidates_repo.add_new()` in `run_search`. It pulls each job's description via a new `searcher.describe(url)`, calls a `RelevanceScorer` (OpenAI-backed) that returns `(score, reason)`, drops below-threshold jobs, and stamps the Summary. Pure helpers (JSON parsing, prompt building, filtering, URL building) are unit-tested; browser/OpenAI glue is not, matching the codebase.

**Tech Stack:** Python 3.13, pytest, OpenAI SDK, patchright/playwright, gspread.

## Global Constraints

- Test interpreter (sender): `sender/.venv/Scripts/python.exe -m pytest`, run from `sender/`.
- TDD: failing test first, minimal code, green, commit.
- Cap AI scoring at **12 jobs per platform per run** (worker and manual), threshold default **60**.
- Feature toggled by `RELEVANCE_ENABLED` (default `true`); when off, behaviour is exactly as today (write all cards, empty Summary, no OpenAI/description calls).
- New `LinkedInSearcher`/`run_search` params are keyword-args with defaults so existing callers/tests keep working.
- Commit message footer (every commit):
  ```
  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01PSWfhYbUPiQ3RKjrsBzCgs
  ```

---

### Task 1: Relevance JSON parsing + prompt builder (pure)

**Files:**
- Create: `sender/app/application/relevance.py`
- Test: `sender/tests/test_relevance.py`

**Interfaces:**
- Produces: `parse_score_response(raw: str) -> tuple[int, str]`;
  `build_score_prompt(profile: str, title: str, description: str) -> tuple[str, str]`
  (returns `(system, user)`); `RelevanceScorer` Protocol with
  `score(profile, title, description) -> tuple[int, str]`.

- [ ] **Step 1: Write the failing test** — create `sender/tests/test_relevance.py`:

```python
from app.application.relevance import build_score_prompt, parse_score_response


def test_parse_clean_json():
    assert parse_score_response('{"score": 82, "reason": "Go backend + AI agents"}') == (
        82, "Go backend + AI agents")


def test_parse_extracts_json_amid_prose_and_clamps():
    assert parse_score_response('Sure: {"score": 200, "reason": "x"} done') == (100, "x")


def test_parse_malformed_returns_zero():
    assert parse_score_response("not json at all") == (0, "")


def test_build_score_prompt_includes_inputs():
    system, user = build_score_prompt("PROF", "TITLE", "DESC")
    assert "JSON" in system or "json" in system
    assert "PROF" in user and "TITLE" in user and "DESC" in user
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest tests/test_relevance.py -v` (from `sender/`)
Expected: FAIL — `ModuleNotFoundError: app.application.relevance`.

- [ ] **Step 3: Write minimal implementation** — create `sender/app/application/relevance.py`:

```python
"""Score a vacancy's fit to the user's search profile (0-100) + a short reason."""
import json
import re
from typing import Protocol

_SCORE_SYSTEM = (
    "Ты оцениваешь, насколько вакансия подходит кандидату по его профилю поиска. "
    "Верни ТОЛЬКО JSON: {\"score\": <целое 0-100>, \"reason\": \"<кратко, до 120 символов>\"}. "
    "score = соответствие ролям, уровню и стеку из профиля. Будь строгим: "
    "не та роль или уровень выше Junior+ — низкий балл."
)


class RelevanceScorer(Protocol):
    def score(self, profile: str, title: str, description: str) -> tuple[int, str]:
        ...


def build_score_prompt(profile: str, title: str, description: str) -> tuple[str, str]:
    user = (
        f"=== ПРОФИЛЬ ПОИСКА ===\n{profile}\n\n"
        f"=== ВАКАНСИЯ ===\nНазвание: {title}\n\n{description}\n\n"
        "Верни только JSON."
    )
    return _SCORE_SYSTEM, user


def parse_score_response(raw: str) -> tuple[int, str]:
    try:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(m.group(0)) if m else {}
        score = max(0, min(100, int(data.get("score", 0))))
        return score, str(data.get("reason", "")).strip()
    except Exception:  # noqa: BLE001 — malformed model output → drop the job
        return 0, ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest tests/test_relevance.py -v` (from `sender/`)
Expected: PASS (4).

- [ ] **Step 5: Commit**

```bash
git add sender/app/application/relevance.py sender/tests/test_relevance.py
git commit -m "feat: relevance JSON parser + score prompt builder"
```

---

### Task 2: `score_and_filter` orchestration (pure)

**Files:**
- Modify: `sender/app/application/relevance.py`
- Test: `sender/tests/test_score_and_filter.py`

**Interfaces:**
- Consumes: `RelevanceScorer`; `Candidate` (mutable dataclass with `.title`, `.url`, `.summary`).
- Produces: `score_and_filter(candidates, describe, scorer, profile, threshold, max_jobs)
  -> list[Candidate]` where `describe` is `Callable[[Candidate], str]`.

- [ ] **Step 1: Write the failing test** — create `sender/tests/test_score_and_filter.py`:

```python
from app.application.relevance import score_and_filter
from app.domain.candidate import Candidate


def _cand(title):
    return Candidate(platform="linkedin", kind="job", url=f"https://x/{title}",
                     title=title, company="Co", salary="", location="", summary="")


class _Scorer:
    def __init__(self, mapping):
        self._m = mapping

    def score(self, profile, title, description):
        return self._m[title]


def test_keeps_only_at_or_above_threshold_and_sets_summary():
    cands = [_cand("A"), _cand("B")]
    scorer = _Scorer({"A": (80, "good fit"), "B": (30, "wrong role")})
    out = score_and_filter(cands, lambda c: "desc", scorer, "P", threshold=60, max_jobs=10)
    assert [c.title for c in out] == ["A"]
    assert out[0].summary == "80/100: good fit"


def test_caps_at_max_jobs():
    cands = [_cand("A"), _cand("B"), _cand("C")]
    scorer = _Scorer({"A": (90, "x"), "B": (90, "y")})  # C never scored
    out = score_and_filter(cands, lambda c: "d", scorer, "P", threshold=10, max_jobs=2)
    assert {c.title for c in out} == {"A", "B"}


def test_describe_failure_skips_only_that_job():
    cands = [_cand("A"), _cand("B")]
    scorer = _Scorer({"A": (90, "ok")})

    def describe(c):
        if c.title == "B":
            raise RuntimeError("page gone")
        return "desc"

    out = score_and_filter(cands, describe, scorer, "P", threshold=10, max_jobs=10)
    assert [c.title for c in out] == ["A"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest tests/test_score_and_filter.py -v` (from `sender/`)
Expected: FAIL — `ImportError: cannot import name 'score_and_filter'`.

- [ ] **Step 3: Write minimal implementation** — append to `sender/app/application/relevance.py`:

```python
def score_and_filter(candidates, describe, scorer, profile, threshold, max_jobs):
    """Score up to `max_jobs` candidates; keep score >= threshold, stamp Summary.

    `describe(candidate) -> str` fetches the job description. A failing describe or
    score skips just that job. Returns the kept candidates (mutated with Summary).
    """
    kept = []
    for c in candidates[:max_jobs]:
        try:
            description = describe(c)
            score, reason = scorer.score(profile, c.title, description)
        except Exception:  # noqa: BLE001 — one bad job never kills the run
            continue
        if score >= threshold:
            c.summary = f"{score}/100: {reason}" if reason else f"{score}/100"
            kept.append(c)
    return kept
```

- [ ] **Step 4: Run test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest tests/test_score_and_filter.py -v` (from `sender/`)
Expected: PASS (3).

- [ ] **Step 5: Commit**

```bash
git add sender/app/application/relevance.py sender/tests/test_score_and_filter.py
git commit -m "feat: score_and_filter caps, filters and stamps candidate Summary"
```

---

### Task 3: Configurable LinkedIn filters (level + recency + location)

**Files:**
- Modify: `sender/app/infrastructure/search/linkedin_search.py` (`build_jobs_url`, `LinkedInSearcher.__init__`, `search`)
- Modify: `sender/app/infrastructure/search/registry.py` (pass config)
- Modify: `sender/app/config.py` (new keys)
- Test: `sender/tests/test_linkedin_url.py`

**Interfaces:**
- Produces: `build_jobs_url(keywords, location, experience="1,2,3", posted_within="r604800") -> str`;
  `LinkedInSearcher(storage_state_path, headless=..., people_enabled=..., experience=..., posted_within=...)`.

- [ ] **Step 1: Write the failing test** — create `sender/tests/test_linkedin_url.py`:

```python
from app.infrastructure.search.linkedin_search import build_jobs_url


def test_url_has_keywords_location_remote_and_defaults():
    url = build_jobs_url("AI Engineer", "Worldwide")
    assert "keywords=AI+Engineer" in url
    assert "location=Worldwide" in url
    assert "f_WT=2" in url            # remote
    assert "f_E=1%2C2%2C3" in url     # Intern + Junior + Junior+
    assert "f_TPR=r604800" in url     # 7 days


def test_empty_experience_omits_level_filter():
    url = build_jobs_url("Dev", "Worldwide", experience="")
    assert "f_E=" not in url


def test_custom_recency_passes_through():
    url = build_jobs_url("Dev", "Worldwide", posted_within="r86400")
    assert "f_TPR=r86400" in url
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest tests/test_linkedin_url.py -v` (from `sender/`)
Expected: FAIL — current `build_jobs_url` hard-codes `f_E=1,2` and `f_TPR=r86400` and takes no `experience`/`posted_within`.

- [ ] **Step 3: Replace `build_jobs_url`** in `linkedin_search.py`:

```python
def build_jobs_url(keywords: str, location: str,
                   experience: str = "1,2,3", posted_within: str = "r604800") -> str:
    qs = {
        "keywords": keywords,
        "location": location,
        "f_WT": "2",            # Remote
        "f_TPR": posted_within,  # recency window
    }
    if experience:
        qs["f_E"] = experience   # 1=Internship,2=Entry/Junior,3=Associate/Junior+
    return f"https://www.linkedin.com/jobs/search/?{urlencode(qs)}"
```

- [ ] **Step 4: Thread the params through `LinkedInSearcher`** — change `__init__` and `search`:

In `__init__`, add params after `people_enabled`:

```python
    def __init__(self, storage_state_path: str, headless: bool = True,
                 people_enabled: bool = False,
                 experience: str = "1,2,3", posted_within: str = "r604800"):
        self._storage_state_path = storage_state_path
        self._headless = headless
        self._people_enabled = people_enabled
        self._experience = experience
        self._posted_within = posted_within
        self._pw = None
        self._browser = None
        self._page = None
```

In `search`, pass them to `build_jobs_url`:

```python
            self._page.goto(build_jobs_url(kw, location, self._experience,
                                           self._posted_within),
                            wait_until="domcontentloaded")
```

- [ ] **Step 5: Add config + registry wiring** — in `sender/app/config.py`, after the
`LINKEDIN_PEOPLE_ENABLED` line:

```python
# LinkedIn level filter (f_E): 1=Internship, 2=Entry/Junior, 3=Associate/Junior+.
# Empty = all levels. Recency f_TPR: r604800 = 7 days.
LINKEDIN_EXPERIENCE = os.environ.get("LINKEDIN_EXPERIENCE", "1,2,3")
LINKEDIN_POSTED_WITHIN = os.environ.get("LINKEDIN_POSTED_WITHIN", "r604800")
```

In `sender/app/infrastructure/search/registry.py`, update the linkedin branch:

```python
    if platform == "linkedin":
        return LinkedInSearcher(
            config.LINKEDIN_STATE_PATH,
            headless=config.BROWSER_HEADLESS,
            people_enabled=config.LINKEDIN_PEOPLE_ENABLED,
            experience=config.LINKEDIN_EXPERIENCE,
            posted_within=config.LINKEDIN_POSTED_WITHIN,
        )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `sender/.venv/Scripts/python.exe -m pytest tests/test_linkedin_url.py tests/test_search_registry.py -v` (from `sender/`)
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add sender/app/infrastructure/search/linkedin_search.py sender/app/infrastructure/search/registry.py sender/app/config.py sender/tests/test_linkedin_url.py
git commit -m "feat: configurable LinkedIn level (Intern/Junior/Junior+) + 7-day recency"
```

---

### Task 4: `describe(url)` on both searchers

**Files:**
- Modify: `sender/app/infrastructure/search/linkedin_search.py` (`LinkedInSearcher.describe`)
- Modify: `sender/app/infrastructure/search/wellfound_search.py` (`WellfoundSearcher.describe`)

**Interfaces:**
- Produces: `LinkedInSearcher.describe(url) -> str`, `WellfoundSearcher.describe(url) -> str`
  (navigate the live session page to the job URL, return description text, `""` on failure).

This is browser glue (no unit test, like `_job_cards`). Selectors include resilient
fallbacks (`main`/`article`) so the method works even if a primary selector drifts.

- [ ] **Step 1: Add `LinkedInSearcher.describe`** — insert after `_job_cards` in `linkedin_search.py`:

```python
    def describe(self, url: str) -> str:
        """Open a job page and return its description text (best-effort)."""
        self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
        self._page.wait_for_timeout(2000)
        for sel in ["#job-details", ".jobs-description__content",
                    ".jobs-box__html-content", ".description__text", "article", "main"]:
            try:
                text = self._page.locator(sel).first.inner_text(timeout=2500)
                if text.strip():
                    return text.strip()[:6000]
            except Exception:  # noqa: BLE001
                continue
        return ""
```

- [ ] **Step 2: Add `WellfoundSearcher.describe`** — insert after `_job_cards` in `wellfound_search.py`:

```python
    def describe(self, url: str) -> str:
        """Open a job page and return its description text (best-effort)."""
        self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
        self._page.wait_for_timeout(3000)
        for sel in ["[data-test='JobDescription']", "div.styles_description__",
                    "div.job-description", "article", "main"]:
            try:
                text = self._page.locator(sel).first.inner_text(timeout=2500)
                if text.strip():
                    return text.strip()[:6000]
            except Exception:  # noqa: BLE001
                continue
        return ""
```

- [ ] **Step 3: Verify the suite still imports/passes (no behaviour change to tested code)**

Run: `sender/.venv/Scripts/python.exe -m pytest -q` (from `sender/`)
Expected: PASS.
Run: `sender/.venv/Scripts/python.exe -c "from app.infrastructure.search.linkedin_search import LinkedInSearcher; from app.infrastructure.search.wellfound_search import WellfoundSearcher; print(hasattr(LinkedInSearcher,'describe'), hasattr(WellfoundSearcher,'describe'))"` (from `sender/`)
Expected: prints `True True`.

- [ ] **Step 4: Commit**

```bash
git add sender/app/infrastructure/search/linkedin_search.py sender/app/infrastructure/search/wellfound_search.py
git commit -m "feat: searcher.describe(url) fetches a job's description text"
```

---

### Task 5: Thread the scorer through `run_search`

**Files:**
- Modify: `sender/app/application/run_search.py`
- Test: `sender/tests/test_run_search.py`

**Interfaces:**
- Consumes: `score_and_filter`; searcher `describe(url)`.
- Produces: `run_search(platforms, searchers, candidates_repo, keywords, location, limit,
  on_error=None, scorer=None, profile="", threshold=0, max_jobs=0) -> int`.

- [ ] **Step 1: Write the failing test** — create `sender/tests/test_run_search.py`:

```python
from app.application.run_search import run_search
from app.domain.candidate import Candidate


def _cand(t):
    return Candidate("linkedin", "job", f"https://x/{t}", t, "Co", "", "", "")


class _Searcher:
    def __init__(self, cands):
        self._cands = cands
        self.described = []

    def start(self): pass
    def search(self, kw, loc, lim): return list(self._cands)
    def describe(self, url): self.described.append(url); return "desc"
    def stop(self): pass


class _Repo:
    def __init__(self): self.added = []
    def add_new(self, cands): self.added.extend(cands); return len(cands)


class _Scorer:
    def score(self, profile, title, description):
        return (90, "fit") if title == "A" else (10, "no")


def test_without_scorer_writes_all_and_never_describes():
    s = _Searcher([_cand("A"), _cand("B")])
    repo = _Repo()
    n = run_search(["linkedin"], {"linkedin": s}, repo, keywords=["x"], location="", limit=10)
    assert n == 2
    assert s.described == []


def test_with_scorer_filters_and_describes():
    s = _Searcher([_cand("A"), _cand("B")])
    repo = _Repo()
    n = run_search(["linkedin"], {"linkedin": s}, repo, keywords=["x"], location="", limit=10,
                   scorer=_Scorer(), profile="P", threshold=60, max_jobs=10)
    assert n == 1
    assert [c.title for c in repo.added] == ["A"]
    assert s.described  # descriptions were fetched
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest tests/test_run_search.py -v` (from `sender/`)
Expected: FAIL — `run_search` takes no `scorer` (TypeError).

- [ ] **Step 3: Update `run_search`** — replace `sender/app/application/run_search.py`:

```python
"""Run one search request: scrape each platform, optionally AI-score, append.

One platform failing neither stops the others nor kills the caller's loop.
Returns the number of new candidates written.
"""
from app.application.relevance import score_and_filter


def run_search(platforms, searchers, candidates_repo, keywords, location, limit,
               on_error=None, scorer=None, profile="", threshold=0, max_jobs=0) -> int:
    added = 0
    for platform in platforms:
        searcher = searchers[platform]
        try:
            searcher.start()
            found = searcher.search(keywords, location, limit)
            if scorer is not None:
                found = score_and_filter(
                    found, lambda c: searcher.describe(c.url),
                    scorer, profile, threshold, max_jobs)
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `sender/.venv/Scripts/python.exe -m pytest tests/test_run_search.py -q` (from `sender/`)
Expected: PASS (2).

- [ ] **Step 5: Commit**

```bash
git add sender/app/application/run_search.py sender/tests/test_run_search.py
git commit -m "feat: run_search optionally AI-scores and filters before writing"
```

---

### Task 6: Wire it up — config, OpenAI scorer, profile file, CLI

**Files:**
- Create: `sender/app/infrastructure/openai_relevance.py`
- Create: `sender/search_profile.txt`
- Modify: `sender/app/config.py` (relevance keys)
- Modify: `sender/app/interface/cli.py` (`_relevance_args`, wire into `run_worker` + `run_search_once`)

**Interfaces:**
- Consumes: `build_score_prompt`, `parse_score_response`, `run_search`'s new kwargs,
  `load_text_file`, `config`.
- Produces: `OpenAIRelevanceScorer(api_key, model)` (a `RelevanceScorer`);
  `_relevance_args() -> dict` (the scorer/profile/threshold/max_jobs kwargs, or `{}` when disabled).

- [ ] **Step 1: Add config** — in `sender/app/config.py`, after `LINKEDIN_POSTED_WITHIN`:

```python
# AI relevance filtering of search results.
RELEVANCE_ENABLED = os.environ.get("RELEVANCE_ENABLED", "true").lower() == "true"
MATCH_THRESHOLD = int(os.environ.get("MATCH_THRESHOLD", "60"))
MATCH_MAX_JOBS = int(os.environ.get("MATCH_MAX_JOBS", "12"))  # per platform per run
SEARCH_PROFILE_PATH = os.environ.get(
    "SEARCH_PROFILE_PATH", str(_ROOT / "sender" / "search_profile.txt"))
```

- [ ] **Step 2: Create the OpenAI scorer** — `sender/app/infrastructure/openai_relevance.py`:

```python
"""OpenAI-backed relevance scorer: one chat call → (score, reason)."""
from openai import OpenAI

from app.application.relevance import build_score_prompt, parse_score_response


class OpenAIRelevanceScorer:
    def __init__(self, api_key: str, model: str):
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def score(self, profile: str, title: str, description: str) -> tuple[int, str]:
        system, user = build_score_prompt(profile, title, description)
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return parse_score_response(resp.choices[0].message.content or "")
```

- [ ] **Step 3: Create the starter search profile** — `sender/search_profile.txt`:

```text
Кого ищу (роли):
- AI Engineer / Prompt Engineer (работа с LLM, в т.ч. Claude Code / агенты)
- Проектирование и построение AI-агентов
- Full-Stack Developer (можно отдельно frontend или backend)

Уровень: Intern / Internship / Junior / Junior+. НЕ middle/senior.

Стек (что знаю и хочу применять):
- Backend: Go, Node.js, Express, NestJS
- Frontend: Vue.js, React, Next.js, Vite
- Базы/инфра: PostgreSQL, MongoDB, Redis
- AI: LLM-приложения, агенты, prompt engineering

Формат: удалённо (remote), любая страна (UAE, USA, Europe, и т.д.).

Что НЕ подходит: middle/senior-позиции, роли без программирования,
узкий не-мой стек (например только PHP/Java/.NET/Ruby), не-remote.
```

- [ ] **Step 4: Wire the CLI** — in `sender/app/interface/cli.py`, add a helper near the top
(after `_notify_done`):

```python
def _relevance_args() -> dict:
    """Kwargs that turn on AI relevance scoring in run_search, or {} when disabled."""
    if not config.RELEVANCE_ENABLED:
        return {}
    from app.infrastructure.cv_loader import load_text_file
    from app.infrastructure.openai_relevance import OpenAIRelevanceScorer
    return dict(
        scorer=OpenAIRelevanceScorer(config.OPENAI_API_KEY, config.OPENAI_MODEL),
        profile=load_text_file(config.SEARCH_PROFILE_PATH),
        threshold=config.MATCH_THRESHOLD,
        max_jobs=config.MATCH_MAX_JOBS,
    )
```

In `run_search_once`, change the `run_search(...)` call to spread the kwargs:

```python
    added = run_search(
        platforms, searchers, candidates,
        keywords=config.SEARCH_KEYWORDS, location=config.SEARCH_LOCATION,
        limit=config.SEARCH_LIMIT_PER_PLATFORM,
        on_error=lambda p, e: print(f"⚠️ {p}: {e}"),
        **_relevance_args(),
    )
```

In `run_worker`, change the `run_one` body's `run_search(...)` call the same way:

```python
        added = run_search(
            plats, searchers, candidates,
            keywords=config.SEARCH_KEYWORDS, location=config.SEARCH_LOCATION,
            limit=config.SEARCH_LIMIT_PER_PLATFORM,
            on_error=lambda p, e: print(f"⚠️ {p}: {e}"),
            **_relevance_args(),
        )
```

- [ ] **Step 5: Run the full sender suite + import smoke**

Run: `sender/.venv/Scripts/python.exe -m pytest -q` (from `sender/`)
Expected: PASS.
Run: `sender/.venv/Scripts/python.exe -c "from app.interface.cli import _relevance_args; from app.infrastructure.openai_relevance import OpenAIRelevanceScorer; print('ok')"` (from `sender/`)
Expected: prints `ok`.

- [ ] **Step 6: Commit**

```bash
git add sender/app/config.py sender/app/infrastructure/openai_relevance.py sender/search_profile.txt sender/app/interface/cli.py
git commit -m "feat: enable AI relevance scoring in worker and one-shot search"
```

---

## Self-Review

**Spec coverage:**
- Fetch description per vacancy → Task 4 (`describe`). ✓
- AI score 0-100 + reason vs search profile → Task 1 (prompt/parse) + Task 6 (OpenAI scorer). ✓
- Keep ≥ threshold, write `score/100: reason` to Summary → Task 2. ✓
- Cap 12 jobs/platform/run (worker + manual) → Task 2 (`max_jobs`) + Task 6 (`MATCH_MAX_JOBS`, both call sites). ✓
- Worldwide → `SEARCH_LOCATION` already defaults to "Worldwide" (no change); Wellfound account note is documentation. ✓
- Intern/Junior/Junior+ levels + looser recency → Task 3 (`LINKEDIN_EXPERIENCE=1,2,3`, `r604800`). ✓
- Search profile file (starter draft) → Task 6 Step 3. ✓
- Config toggle `RELEVANCE_ENABLED` + threshold/max → Task 6 Step 1, applied via `_relevance_args`. ✓
- Tests for `parse_score_response`, `score_and_filter`, `build_jobs_url` → Tasks 1, 2, 3. ✓

**Placeholder scan:** No TBD/TODO; every code step has full code. The `describe()` selectors are concrete lists with `main`/`article` fallbacks (browser glue, no unit test — same convention as `_job_cards`). ✓

**Type consistency:** `score(profile, title, description) -> (int, str)` used identically in the Protocol (Task 1), fakes (Tasks 2/5), and `OpenAIRelevanceScorer` (Task 6). `score_and_filter(candidates, describe, scorer, profile, threshold, max_jobs)` and `run_search(..., scorer, profile, threshold, max_jobs)` line up. `build_jobs_url(keywords, location, experience, posted_within)` matches the searcher call and registry wiring. ✓

**Ordering note:** Task 5 imports `score_and_filter` (Task 2) and relies on searcher `describe` (Task 4) only at runtime; the unit test uses a fake searcher, so Tasks can be implemented in order 1→6 with every suite green in between. Task 6's `run_search` calls use `**_relevance_args()`, which is `{}` until `RELEVANCE_ENABLED` + the profile file exist (both delivered in Task 6).
