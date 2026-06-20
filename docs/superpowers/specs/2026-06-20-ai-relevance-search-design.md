# AI-relevance vacancy search — design

**Date:** 2026-06-20
**Status:** Approved (pending spec review)

## Problem

Search currently keyword-matches job titles only (`SEARCH_KEYWORDS` fed to LinkedIn/
Wellfound) and writes every card to «Кандидаты» with an empty `Summary`. The user
wants results judged the way a person would — by reading the **job description** and
deciding whether it fits their target roles — and wants results **worldwide**, not
restricted to Europe. Today's LinkedIn query is also hard-pinned to entry-level and
the last 24h, which drops relevant mid-level / older postings.

## Goals

1. For each found vacancy, fetch its **description**, have an AI score relevance
   (0-100) against a user-written **search profile**, and keep only score ≥ threshold.
2. Write `score/100 — reason` into the existing `Summary` column (shows in the bot card).
3. Cap AI scoring at **12 jobs per platform per run** (worker and manual alike) to bound
   cost/time.
4. Search **worldwide** (remote anywhere), and loosen LinkedIn's experience/recency
   pins so the AI — not a crude filter — decides relevance.
5. Everything configurable via `.env`; feature can be turned off (`RELEVANCE_ENABLED`).

## Non-goals

- No autonomous browsing agent (computer-use). We scrape descriptions and make one
  OpenAI call per job.
- Judging against the CV. The criterion is the **search profile** text only (per the
  user's choice). The CV stays for message generation, untouched.
- Changing Wellfound's account location. Wellfound's "Europe" restriction comes from the
  user's Wellfound **profile** location setting, not our code; documented as a manual step.

## Architecture & components

### 1. Search profile (`sender/search_profile.txt`, new)
A short user-written text: target roles, level, stack, remote preference. Loaded via the
existing `load_text_file`. `SEARCH_PROFILE_PATH` in config (default points at this file; an
env override may point elsewhere). The file is committed (job preferences, not a secret).
A starter draft is committed describing: AI/Prompt Engineer (Claude Code), Full-Stack
(Go / Node / Express / NestJS / Vue / React / Next / Vite / Redis / Postgres / Mongo),
AI-agent design/build, frontend or backend, remote worldwide.

### 2. Relevance scorer (application + infrastructure)
- `app/application/relevance.py`:
  - `RelevanceScorer` protocol: `score(profile, title, description) -> tuple[int, str]`.
  - `parse_score_response(raw: str) -> tuple[int, str]` — pure parser of the model's JSON
    (`{"score": int, "reason": str}`), clamps score to 0-100, tolerates malformed input
    (returns `(0, "")`). Unit-tested.
  - `score_and_filter(candidates, describe, scorer, profile, threshold, max_jobs)
    -> list[Candidate]` — pure orchestration: take at most `max_jobs`; for each, call
    `describe(candidate)` for the description, `scorer.score(...)`, keep when
    `score >= threshold`, set `summary = f"{score}/100 — {reason}"`. A failing
    describe/score skips that one job (never kills the run). Unit-tested with fakes.
- `app/infrastructure/openai_relevance.py`: `OpenAIRelevanceScorer` implementing the
  protocol via the existing OpenAI client — one chat call returning the JSON, parsed by
  `parse_score_response`.

### 3. Description fetching (per searcher)
- `LinkedInSearcher.describe(url) -> str` and `WellfoundSearcher.describe(url) -> str`:
  navigate the already-open session page to the job URL and return the description text.
  (Exact selectors discovered live at implementation time, as with the card selectors;
  isolated in these methods. Return `""` on failure.)
- Search no longer needs the results page after `search()` returns the cards, so
  `describe()` may navigate freely.

### 4. Pipeline wiring (`run_search`)
`run_search` gains optional `scorer`, `profile`, `threshold`, `max_jobs`. When `scorer`
is set:
```
found = searcher.search(keywords, location, limit)
found = score_and_filter(found, lambda c: searcher.describe(c.url),
                         scorer, profile, threshold, max_jobs)
added += candidates_repo.add_new(found)
```
When `scorer` is None, behaviour is exactly as today (write all, empty summary).
`run_worker` and `run_search_once` build an `OpenAIRelevanceScorer` + load the profile and
pass them through when `RELEVANCE_ENABLED`.

### 5. Worldwide location + looser LinkedIn filters
- `SEARCH_LOCATION` default `"Worldwide"`.
- `LinkedInSearcher.build_jobs_url` takes the experience and recency filters from config
  instead of hard-coding them:
  - `LINKEDIN_EXPERIENCE` (default `""` = all levels; was `f_E=1,2`).
  - `LINKEDIN_POSTED_WITHIN` (default `r604800` = 7 days; was `r86400` = 24h).
  - keeps `f_WT=2` (remote).
- Wellfound: documented manual step — set the Wellfound profile location to Worldwide/
  Remote; code already sends `remote=true`.

## Config additions (`sender`, all optional)
- `RELEVANCE_ENABLED` (default `true`)
- `MATCH_THRESHOLD` (default `60`)
- `MATCH_MAX_JOBS` (default `12`, per platform per run)
- `SEARCH_PROFILE_PATH` (default `sender/search_profile.txt`)
- `SEARCH_LOCATION` (default `Worldwide`)
- `LINKEDIN_EXPERIENCE` (default `""`), `LINKEDIN_POSTED_WITHIN` (default `r604800`)

## Data flow
```
run_search(platform)
  searcher.start()
  cards = searcher.search(keywords, SEARCH_LOCATION, limit)     # title/company/url
  if RELEVANCE_ENABLED:
     kept = score_and_filter(cards[:MATCH_MAX_JOBS],
              describe=searcher.describe,        # opens each job page → description
              scorer=OpenAIRelevanceScorer,      # 1 OpenAI call → {score, reason}
              profile=search_profile.txt,
              threshold=MATCH_THRESHOLD)          # drop < threshold; set Summary
  candidates_repo.add_new(kept)                   # dedup → «Кандидаты»
  searcher.stop()
```

## Error handling
- Per-job: a failing `describe()` or `scorer.score()` skips that job (logged via the
  existing `on_error`/print), others continue.
- Whole-platform failures stay isolated by `run_search`'s existing try/except.
- Malformed model output → `parse_score_response` returns `(0, "")` → job dropped (below
  any sane threshold), never crashes.
- `RELEVANCE_ENABLED=false` → no OpenAI calls, no description fetch, today's behaviour.

## Testing (TDD)
Unit-tested (pure):
- `parse_score_response`: valid JSON, extra prose around JSON, malformed → `(0, "")`,
  score clamping.
- `score_and_filter`: caps at `max_jobs`; drops below threshold; sets
  `summary="<score>/100 — <reason>"`; a raising `describe` skips just that job.
- `LinkedInSearcher.build_jobs_url`: includes configured experience/recency/location and
  the remote flag; empty experience omits `f_E`.

Not live-tested (consistent with the codebase): the OpenAI call, the description-page
scraping, the browser navigation.

## Open risks
- **Speed/cost:** each run now opens up to 12 job pages per platform and makes up to 12
  OpenAI calls per platform. A run goes from ~10s to minutes. `MATCH_MAX_JOBS=12` bounds it.
- **Description selectors** will drift like the card selectors; isolated in `describe()` and
  discovered against the live DOM during implementation.
