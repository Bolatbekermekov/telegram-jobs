# Multi-platform search triggers — design

**Date:** 2026-06-20
**Status:** Approved (pending spec review)

## Problem

Today vacancy search is reachable only one way: the Telegram bot's `/start_search`
queues an "all" request in the «Команды» tab, and the always-on `make worker` loop
drains it. There is:

- no scheduled auto-search (the user must trigger every run by hand);
- no per-platform trigger (can only search "all");
- no Makefile entry to run a search for testing without the worker loop;
- no menu registration, so the bot's commands are invisible in Telegram's UI;
- a `make wellfound` command that conflates **login** and **search**, while
  Wellfound's Cloudflare Turnstile can only be passed by a human-driven Chrome.

The user wants: one always-on `make worker` that auto-searches all platforms a few
times a day, **plus** separate one-shot per-platform triggers — in both the Makefile
and the bot — that run without stopping the worker. Wellfound login is split into its
own command; its search rides the warm Chrome that login leaves open.

## Goals

1. `make worker`: always-on; auto-search all platforms every `SEARCH_EVERY_HOURS`
   (default 8 ≈ 3×/day); still drains bot-queued requests; emits heartbeat.
2. One-shot Makefile triggers: `make search`, `make search_linkedin`,
   `make search_wellfound` — standalone processes that do not touch the worker.
3. Per-platform bot commands: `/search_linkedin`, `/search_wellfound` (alongside the
   existing `/start_search` = all). Each queues one request; the worker executes it.
4. `make bot_menu`: register the bot's command list via Telegram `setMyCommands` so the
   commands show in the client's menu.
5. Rename `make wellfound` → `make login_wellfound` (login only; leaves Chrome open).
   Wellfound search attaches to that warm Chrome over CDP.

## Non-goals

- Solving Wellfound Cloudflare for a *headless / unattended* browser. Wellfound search
  only works while the user's `login_wellfound` Chrome is open; otherwise it is skipped.
- Wall-clock slot scheduling (e.g. exactly 09:00/14:00/19:00). We use a simple elapsed-
  interval check (`SEARCH_EVERY_HOURS`), which is good enough for "~3×/day".
- Persisting the worker's last-auto-search time across restarts. In-memory is fine; a
  restart simply triggers one auto-search shortly after start.

## Command map (final)

### Logins (interactive, one-time)
| Command | Logs in |
|---|---|
| `make login_telegram` | Telegram (QR) |
| `make login_browser` | LinkedIn |
| `make login_wellfound` | Wellfound — opens the user's Chrome (debug port), they pass Cloudflare + log in, Chrome stays open |

### Search
| Command | Behaviour |
|---|---|
| `make worker` | Always-on. Every `SEARCH_EVERY_HOURS` runs an all-platform auto-search; also drains bot-queued requests; heartbeats. |
| `make search` | One-shot, all platforms, then exits. |
| `make search_linkedin` | One-shot, LinkedIn only. |
| `make search_wellfound` | One-shot, Wellfound only (needs the `login_wellfound` Chrome open). |
| `make bot_menu` | One-time: register the bot command menu via `setMyCommands`. |

### Bot commands (visible after `make bot_menu`)
| Command | Behaviour |
|---|---|
| `/start_search` | Queue an "all" search request (existing). |
| `/search_linkedin` | Queue a "linkedin" search request (new). |
| `/search_wellfound` | Queue a "wellfound" search request (new). |
| `/show_vacancies`, `/status` | Unchanged. |

Bot commands queue into «Команды»; the worker executes them. Standalone `make search*`
run in their own process. Neither stops the worker.

## Architecture & components

### 1. Worker scheduler (`sender`)
- New config: `SEARCH_EVERY_HOURS = int(env, default 8)`.
- New pure helper `should_auto_search(last_run, now, every_hours) -> bool` in the
  application layer — testable without time mocking via injected datetimes.
- `run_worker()` keeps calling `worker_tick(control, run_one)` each poll (drains the
  bot queue, unchanged). Additionally, each poll it checks `should_auto_search`; when
  true it runs `run_one` for an all-platform request and records `last_run = now`
  (in-memory). On first start `last_run` is unset → one auto-search runs promptly.

### 2. One-shot search command (`sender`)
- New application helper `run_search_once(platforms)` in `cli.py` that builds the
  gspread book + `CandidatesRepo`, builds searchers via the registry, calls the
  existing `run_search(...)`, prints the added count, and exits. Reused by all three
  Makefile one-shot targets.
- New pure helper `platforms_arg(token) -> list[str]` mapping the CLI token
  (`search` | `search_linkedin` | `search_wellfound`) to platform list, reusing
  `platforms_for`. Testable.
- `run.py` dispatch gains `search`, `search_linkedin`, `search_wellfound`; renames the
  `wellfound` subcommand to `login_wellfound`.

### 3. Wellfound: login-only + warm-Chrome search
- `run_wellfound()` (cli) is split:
  - `run_login_wellfound()`: launches the user's Chrome via
    `build_chrome_debug_args(...)`, prompts the user to pass Cloudflare + log in, on
    Enter does a quick CDP sanity check (attached page is not the "Один момент…"
    challenge), prints OK, and **exits leaving Chrome running**.
  - Search no longer lives here; it goes through `run_search_once` / the worker.
- `registry.build_searcher("wellfound")` returns `WellfoundSearcher(...,
  cdp_url=config.WELLFOUND_CDP_URL)` (attach mode) instead of launch mode, so every
  search path uses the warm Chrome.
- `run_search`'s existing per-platform `on_error` isolation already covers "Chrome not
  open / CDP unreachable": Wellfound errors, other platforms proceed.

### 4. Bot per-platform commands (`intake-bot`)
- `_handle_command` gains exact-prefix routes for `/search_linkedin` and
  `/search_wellfound`, each calling `ControlGateway.queue_search(<platform>)` and
  replying via `start_search_reply(online)` (same UX as `/start_search`).
- `/start` help text updated to list the new commands.

### 5. Bot menu registration (`make bot_menu`)
- New script `sender/register_bot_menu.py` (runs locally, uses `TELEGRAM_BOT_TOKEN`)
  that POSTs `setMyCommands` with the command list + Russian descriptions. Pure helper
  `bot_commands_payload() -> list[dict]` is unit-tested; the HTTP POST is a thin wrapper.

## Data flow

```
Bot /search_linkedin ─→ queue_search("linkedin") ─→ «Команды» (pending)
                                                        │
make worker (poll) ── worker_tick ── drains pending ──→ run_one(req) ─→ run_search
make worker (poll) ── should_auto_search? ── yes ─────→ run_one(all)  ─┘
make search_linkedin ─────────────────────────────────→ run_search_once(["linkedin"])
                                                              │
                              run_search ── per platform ─────┤
                                LinkedIn: launch headless Chromium (linkedin_state.json)
                                Wellfound: connect_over_cdp(WELLFOUND_CDP_URL) → warm Chrome
                                                              │
                                            CandidatesRepo.add_new (dedup) → «Кандидаты»
```

## Error handling

- Per-platform failures are isolated by `run_search`'s `on_error` (existing). Wellfound
  with no warm Chrome → connection error → skipped; LinkedIn still runs.
- `make login_wellfound`: if `CHROME_PATH` is wrong → clear message, exit. If after Enter
  the attached page is still the Cloudflare challenge → warn that login didn't complete.
- Worker auto-search errors never kill the loop (existing `worker_tick` + try/except).
- Concurrent LinkedIn searches (worker + a standalone `make search_linkedin`) are safe:
  separate browser instances reading the same `linkedin_state.json` (read-only); the
  candidate dedup prevents duplicate sheet rows.

## Testing (TDD)

Pure/unit-tested:
- `should_auto_search(last_run, now, every_hours)` — unset last_run, not-yet-elapsed,
  elapsed.
- `platforms_arg(token)` — the three tokens map to the right platform lists.
- `bot_commands_payload()` — includes the per-platform commands with descriptions.
- `_handle_command` routing for `/search_linkedin` and `/search_wellfound` (intake-bot),
  asserting the right `queue_search` platform via a fake gateway.

Not live-tested (browser/Cloudflare/HTTP), consistent with the rest of the codebase:
the CDP attach, the `setMyCommands` POST, and the actual scrape.

## Config additions (`sender`)
- `SEARCH_EVERY_HOURS` (default `8`).
- (Reuses existing `CHROME_PATH`, `WELLFOUND_CDP_PORT`, `WELLFOUND_CDP_URL`,
  `WELLFOUND_CHROME_PROFILE` added in the Wellfound-Cloudflare fix.)

## Open risk

Wellfound search via CDP through the warm Chrome is **not yet verified live** — the
first real check is `make search_wellfound` after `make login_wellfound`. If CDP-driven
navigation re-triggers Cloudflare despite the warm `cf_clearance`, the fallback is to
scrape the page the user already opened (no `goto`). Selector drift in Wellfound's DOM
is a separate, known follow-up.
