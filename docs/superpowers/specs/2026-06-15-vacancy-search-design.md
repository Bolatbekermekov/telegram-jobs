# Vacancy search automation (sub-project C)

**Date:** 2026-06-15
**Status:** design approved, spec under review

## Context

Sub-projects B (multi-platform sending) and A (intake auto-detection) are done.
B made the sender apply/message across `telegram | email | linkedin | hh |
wellfound`; A made the intake bot auto-detect platform/target from pasted text
and write leads to the main Google Sheet.

Sub-project C adds the missing front of the funnel: **automatically discovering
internship/junior vacancies** on LinkedIn and Wellfound, letting the user curate
them from the phone, and feeding the chosen ones into the same leads pipeline the
sender already drains.

Only LinkedIn and Wellfound are in scope for search (HeadHunter/Email are
send-only; they have no "browse fresh roles" flow we want to automate here).

## Goal

A background worker periodically scrapes LinkedIn + Wellfound for junior/intern
roles and silently accumulates them as **candidates** in a separate sheet tab.
From Telegram the user reviews candidates 7 at a time and approves/rejects each;
approved candidates become normal `new` leads in the main tab, which the existing
sender then applies to / messages. The user can also trigger a fresh scrape on
demand. The only hard requirement is "laptop on"; everything else is driven from
the phone.

## Why the scraper runs on the laptop (not Vercel)

Browser scraping of LinkedIn/Wellfound cannot sensibly run on Vercel serverless:
datacenter IPs are flagged/banned by LinkedIn within tens of requests
(residential IP required); there is no persistent logged-in session and no way to
re-login interactively on serverless; Chromium-in-Python barely fits the size
limit; and human-paced multi-page scraping can exceed function time limits. The
laptop is a residential IP with a persistent saved session, so the scraper lives
in `sender/` (where the Playwright login sessions already exist). The Vercel
webhook keeps its role: receiving Telegram commands/button taps. The two sides
communicate **only through the Google Sheet** (no new database, no second bot).

## Architecture

```
LAPTOP (residential IP, persistent login) — one worker process:
  python -m app worker
    loop every ~60s:
      - heartbeat: write last_seen = now() to control tab
      - read «Команды» for status=pending search requests
      - if a scheduled time is due and not run recently -> synthesize a request
      - for each request (status running): scrape platforms SEQUENTIALLY
          linkedin -> wellfound  (one browser session per platform per run)
          for each candidate: dedup -> append to «Кандидаты» (pending), cap 15/platform
        mark request done (or error per platform; never kill the loop)

PHONE (Telegram, existing bot, webhook on Vercel):
  /start_search   -> if heartbeat fresh: write pending request, reply "🔎 запускаю"
                     else: warn "ноут офлайн" AND still queue the request
  /show_vacancies -> read up to 7 pending candidates, send each with ✅/❌ buttons
  ✅ approve:<id>  -> candidate -> main tab (status=new); candidate -> taken; edit msg
  ❌ skip:<id>     -> candidate -> rejected; edit msg

SENDER (unchanged except one branch):
  python -m app send  drains main tab (status=new), applies/messages as before
```

Candidate accumulation (worker / `/start_search`) needs the laptop. Review
(`/show_vacancies`, buttons) is pure sheet read/write via the Vercel webhook and
works even with the laptop off.

## Components

### `sender/` — search worker

- **`domain/candidate.py`** (new, pure)
  ```python
  @dataclass
  class Candidate:
      platform: str    # linkedin | wellfound
      kind: str        # job | profile  (linkedin profiles are recruiter DMs)
      url: str
      title: str
      company: str
      salary: str      # "" if the platform does not expose it
      location: str
      summary: str
  def normalize_url(url: str) -> str          # dedup key: lower host, drop query/fragment/trailing slash
  def linkedin_action_for_url(url: str) -> str # "/jobs/" -> "easy_apply", "/in/" -> "dm"
  ```

- **`domain/search_request.py`** (new, pure) — `SearchRequest(id, platform, status)`
  where `platform` is `all | linkedin | wellfound` and `status` is
  `pending | running | done | error`.

- **`infrastructure/search/linkedin_search.py`** (new) — Playwright. Opens
  LinkedIn's own search URL with filters and reads result cards; raw DOM
  extraction isolated in a pure `parse_*` function (selectors drift, like
  `fill_and_send`). Two modes:
  - jobs: `linkedin.com/jobs/search/?keywords=<q>&f_E=1,2&f_WT=2&location=Worldwide&f_TPR=r86400`
    (`f_E` 1=intern/2=entry, `f_WT=2` remote, `f_TPR=r86400` last 24h) →
    `title, company, location, url=/jobs/view/<id>`, `kind=job`. LinkedIn rarely
    shows salary → `salary=""`.
  - profiles (recruiters, behind `LINKEDIN_PEOPLE_ENABLED` flag — fragile, ban-prone):
    `linkedin.com/search/results/people/?keywords=<q>` → `title=name`,
    `company=headline`, `url=/in/<slug>`, `kind=profile`.

- **`infrastructure/search/wellfound_search.py`** (new) — Playwright. Wellfound
  jobs search with role/remote filters → `title, company, salary, location,
  url`, `kind=job`. Wellfound usually exposes salary.

- **`infrastructure/search/registry.py`** (new) — `build_searcher(platform)` →
  the right searcher; mirrors `channels/registry.py`.

- **`infrastructure/candidates_repo.py`** (new) — reads/writes the «Кандидаты»
  tab; `add(candidate)` (skips if `normalize_url` already present in «Кандидаты»
  OR the main tab, and if platform already holds 15 pending it does not add);
  `pending(limit, platform=None)`; `mark(id, status)`; `get(id)`.

- **`infrastructure/control_repo.py`** (new) — «Команды» tab: `pending_requests()`,
  `mark(id, status)`, `add_request(platform)`, plus heartbeat `touch()` /
  `last_seen()`.

- **`application/run_search.py`** (new, pure orchestration for ONE request) —
  given searchers + candidates_repo + notifier(optional): scrape each platform in
  order, dedup, append new candidates, mark request done; per-platform `try/except`
  so one platform failing neither stops the others nor kills the loop. Tested with
  fakes (no browser/network).

- **`interface/cli.py`** (modify) — add `worker` subcommand (the loop: heartbeat,
  poll control tab, run schedule, call `run_search`) and a `search` one-shot for
  debugging. Existing `send` unchanged.

- **`config.py`** (modify) — search keywords (`internship`, `junior`), location
  (remote/worldwide), `SEARCH_LIMIT_PER_PLATFORM=15`, `SHOW_BATCH=7`,
  `POLL_INTERVAL≈60s`, per-platform daily schedule times, per-platform
  `storage_state` paths, `LINKEDIN_PEOPLE_ENABLED` flag, human-pacing delay range
  (2–6s), `HEARTBEAT_STALE_SECONDS≈180`.

### New sheet tab «Кандидаты»

`id · Платформа · Тип · URL · Title · Company · Salary · Location · Summary · Статус · Дата`
Статус: `pending → taken | rejected`. The main leads tab keeps its 10-column
layout (unchanged); approval appends a row there with `Платформа`, `Цель`=URL,
`Вакансия`=title+summary, `Статус`=new.

### New sheet tab «Команды» (control + heartbeat)

`id · platform · status · created_at · done_at` plus a single heartbeat cell
(`last_seen`). The phone writes requests here; the worker reads them and stamps
its heartbeat.

### `intake-bot/` — webhook (modify)

- Handle commands: `/start_search` (heartbeat check → write pending request +
  appropriate reply), `/show_vacancies` (read ≤7 pending candidates, send one
  message each with `✅ approve:<id>` / `❌ skip:<id>` inline buttons; each shows a
  platform badge, title — company, salary · location, short summary).
- Handle `callback_query`: `approve:<id>` promotes the candidate to the main tab
  (status=new) and marks it `taken`, then edits the message to «✅ Взято»;
  `skip:<id>` marks it `rejected` and edits to «❌ Скип». Idempotent if the id is
  already taken/missing.
- Reuse the existing sheets access; add thin candidate/control repos on the intake
  side (or share by reading the same tabs).

### `sender/` — apply path (one change)

`LinkedInChannel.send()` branches on the target URL via `linkedin_action_for_url`:
`/jobs/...` → new `easy_apply_via_page()` (Easy Apply flow), `/in/...` → existing
`fill_and_send()` (DM). Wellfound already applies. Telegram/email/hh unchanged.

## Telegram message (one per candidate)

```
🔵 LinkedIn · вакансия
Junior Backend Engineer — Acme Inc
💰 $40–55k · 📍 Remote (Worldwide)
📝 Python/Django, 0–2 года, англ. B2…
```
`[ ✅ Approve ]  [ ❌ Not ]`   ← callback_data `approve:<id>` / `skip:<id>`
(Wellfound badge `🅰️ Wellfound`; salary shows `—` when absent.)

## Limits

- **15 candidates per platform** held as `pending` (worker stops adding past the
  cap; `rejected`/`taken` rows do not count). Applies to both the scheduled worker
  and `/start_search`.
- **7 per `/show_vacancies`** batch; the next call shows the next 7.
- **Anti-ban pacing:** 2–6s randomized delays between actions, one browser session
  per platform per run, no pagination beyond the first results page, platforms
  scraped sequentially.

## Error handling

- Scraper fails / login expired → caught per platform; reply «⚠️ LinkedIn: вход
  слетел / селектор изменился»; that platform's request part is `error`, others
  continue; loop survives.
- `/start_search` while laptop offline (stale heartbeat) → warn «⚠️ ноут офлайн»
  AND queue the request (`pending`); the worker runs it when it next polls.
- `/show_vacancies` / buttons → pure sheet ops, work with laptop off.
- `approve:` on an already-taken/missing id → idempotent, no duplicate row.
- Notifier send failure during scrape → candidate already saved; safe to re-notify;
  logged.
- Worker fatal error → top-level `try`; logged; OS autostart restarts the process.

## Testing

Pure / fake-driven (no browser, no network):
- `normalize_url` (dedup equivalence), `linkedin_action_for_url` (jobs vs profile).
- `candidates_repo.add` dedup + 15/platform cap (fake sheet).
- `run_search` with fake searcher + fake repo + fake notifier: writes only new
  candidates, respects the cap, survives a searcher raising, marks the request done.
- DOM `parse_*` functions on fake Playwright pages (LinkedIn jobs/profiles,
  Wellfound jobs).
- Webhook: `/start_search` writes a request (fresh vs stale heartbeat); `/show_vacancies`
  reads ≤7 and builds buttons; `approve` promotes to main tab + marks taken;
  `skip` marks rejected; idempotency on repeat.

## Out of scope (C)

- Per-platform review commands (chose: single `/show_vacancies` + `/start_search`).
- Auto-applying without review (approval is always manual via buttons).
- Moving the scraper off the laptop (VPS + residential proxy is a later option;
  the port-based design allows it without rewriting logic).
- Boards other than LinkedIn/Wellfound.
