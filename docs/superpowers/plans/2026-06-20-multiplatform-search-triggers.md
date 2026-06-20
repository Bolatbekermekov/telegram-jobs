# Multi-platform Search Triggers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an always-on worker auto-search (~3×/day) plus one-shot per-platform search triggers in both the Makefile and the Telegram bot, register the bot command menu, and split Wellfound login (`make login_wellfound`, leaves a warm Chrome open) from search (worker / `make search_wellfound`, via CDP).

**Architecture:** All search paths funnel through the existing `run_search(platforms, searchers, candidates_repo, ...)` pipeline. Pure decision/mapping helpers (`should_auto_search`, `platforms_arg`, `command_to_search_platform`, `bot_commands_payload`) are unit-tested; gspread/browser/HTTP glue mirrors the existing `run_worker` wiring and is not live-tested, consistent with the codebase. Wellfound's searcher attaches over CDP to the user's warm Chrome (already supported via `WellfoundSearcher(cdp_url=...)`).

**Tech Stack:** Python 3.13, pytest, gspread, patchright/playwright, FastAPI (intake-bot), Telegram Bot API.

## Global Constraints

- Test interpreter (sender): `sender/.venv/Scripts/python.exe -m pytest`, run from the `sender/` directory.
- Test interpreter (intake-bot): same venv, run from the `intake-bot/` directory. **Never** run both suites together (both have `tests/conftest.py` → `ImportPathMismatchError`).
- TDD: failing test first, minimal code, green, commit.
- `PYTHON ?= sender/.venv/Scripts/python.exe` in the Makefile; targets run from project root.
- Wellfound search only works while the `make login_wellfound` Chrome is open; otherwise it is skipped per-platform (never crashes other platforms).
- Do not commit secrets; `.env`, `*_state.json`, `sender/.wellfound_chrome/` stay gitignored.
- Commit message footer (every commit):
  ```
  Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01PSWfhYbUPiQ3RKjrsBzCgs
  ```

---

### Task 1: Wellfound searcher → CDP mode in the registry

**Files:**
- Modify: `sender/app/infrastructure/search/registry.py:14-18`
- Test: `sender/tests/test_search_registry.py`

**Interfaces:**
- Consumes: `WellfoundSearcher(storage_state_path, headless=..., cdp_url=...)` and its `uses_cdp` property (already implemented); `config.WELLFOUND_CDP_URL` (already in config).
- Produces: `build_searcher("wellfound")` returns a searcher with `uses_cdp is True`.

- [ ] **Step 1: Write the failing test** — append to `sender/tests/test_search_registry.py`:

```python
def test_wellfound_uses_cdp():
    s = build_searcher("wellfound")
    assert s.uses_cdp is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest tests/test_search_registry.py::test_wellfound_uses_cdp -v` (from `sender/`)
Expected: FAIL — `uses_cdp is False` (registry still builds launch mode).

- [ ] **Step 3: Write minimal implementation** — in `registry.py` change the wellfound branch:

```python
    if platform == "wellfound":
        return WellfoundSearcher(
            config.WELLFOUND_STATE_PATH,
            headless=config.BROWSER_HEADLESS,
            cdp_url=config.WELLFOUND_CDP_URL,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `sender/.venv/Scripts/python.exe -m pytest tests/test_search_registry.py -v` (from `sender/`)
Expected: PASS (all 4).

- [ ] **Step 5: Commit**

```bash
git add sender/app/infrastructure/search/registry.py sender/tests/test_search_registry.py
git commit -m "feat: wellfound searcher attaches to warm Chrome via CDP in registry"
```

---

### Task 2: `platforms_arg` helper + one-shot search command + Makefile targets

**Files:**
- Create: `sender/app/application/search_commands.py`
- Test: `sender/tests/test_search_commands.py`
- Modify: `sender/app/interface/cli.py` (add `run_search_once`)
- Modify: `sender/run.py` (dispatch `search` / `search_linkedin` / `search_wellfound`)
- Modify: `Makefile` (new targets)

**Interfaces:**
- Consumes: `platforms_for` from `app.domain.search_request`; `run_search`, `CandidatesRepo`, `build_searcher`, `config`.
- Produces: `platforms_arg(token: str) -> list[str]`; `run_search_once(platforms: list[str]) -> None`.

- [ ] **Step 1: Write the failing test** — create `sender/tests/test_search_commands.py`:

```python
from app.application.search_commands import platforms_arg


def test_search_token_means_all_platforms():
    assert platforms_arg("search") == ["linkedin", "wellfound"]


def test_per_platform_tokens():
    assert platforms_arg("search_linkedin") == ["linkedin"]
    assert platforms_arg("search_wellfound") == ["wellfound"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest tests/test_search_commands.py -v` (from `sender/`)
Expected: FAIL — `ModuleNotFoundError: app.application.search_commands`.

- [ ] **Step 3: Write minimal implementation** — create `sender/app/application/search_commands.py`:

```python
"""Map a CLI subcommand token to the concrete platforms to search."""
from app.domain.search_request import platforms_for

_TOKEN_TO_PLATFORM = {
    "search": "all",
    "search_linkedin": "linkedin",
    "search_wellfound": "wellfound",
}


def platforms_arg(token: str) -> list[str]:
    return platforms_for(_TOKEN_TO_PLATFORM[token])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest tests/test_search_commands.py -v` (from `sender/`)
Expected: PASS.

- [ ] **Step 5: Add `run_search_once` to `cli.py`** — insert after `run_worker` (before `run_login_browser`):

```python
def run_search_once(platforms):
    """One-shot search across `platforms`, write candidates, then exit.

    Standalone process (does not touch the worker). Wellfound rides the warm
    Chrome from `make login_wellfound` via CDP; if it is closed, Wellfound is
    skipped and the other platforms still run.
    """
    import gspread
    from google.oauth2.service_account import Credentials

    from app.application.run_search import run_search
    from app.infrastructure.candidates_repo import CandidatesRepo
    from app.infrastructure.search.registry import build_searcher

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(config.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=scopes)
    book = gspread.authorize(creds).open_by_key(config.SHEET_ID)
    candidates = CandidatesRepo(
        book.worksheet(config.CANDIDATES_TAB), book.worksheet(config.SHEET_TAB),
        config.SEARCH_LIMIT_PER_PLATFORM)
    searchers = {p: build_searcher(p) for p in platforms}
    print(f"Ищу вакансии: {', '.join(platforms)}...")
    added = run_search(
        platforms, searchers, candidates,
        keywords=config.SEARCH_KEYWORDS, location=config.SEARCH_LOCATION,
        limit=config.SEARCH_LIMIT_PER_PLATFORM,
        on_error=lambda p, e: print(f"⚠️ {p}: {e}"),
    )
    print(f"Готово. Новых кандидатов записано: {added}.")
```

- [ ] **Step 6: Wire `run.py` dispatch** — replace the import + `__main__` block in `sender/run.py`:

```python
from app.interface.cli import (  # noqa: E402
    run,
    run_login_browser,
    run_search_once,
    run_wellfound,
    run_worker,
)

if __name__ == "__main__":
    cmd = sys.argv[1:2]
    if cmd == ["worker"]:
        run_worker()
    elif cmd == ["login_browser"]:
        run_login_browser()
    elif cmd == ["wellfound"]:
        run_wellfound()
    elif cmd and cmd[0] in ("search", "search_linkedin", "search_wellfound"):
        from app.application.search_commands import platforms_arg
        run_search_once(platforms_arg(cmd[0]))
    else:
        run()
```

(Note: `run_wellfound` is renamed to `run_login_wellfound` in Task 4; this block is updated there.)

- [ ] **Step 7: Add Makefile targets** — add to `.PHONY` and add target bodies:

```makefile
search:
	$(PYTHON) sender/run.py search

search_linkedin:
	$(PYTHON) sender/run.py search_linkedin

search_wellfound:
	$(PYTHON) sender/run.py search_wellfound
```

Update the `.PHONY` line to include `search search_linkedin search_wellfound`, and add comment lines near the top:

```makefile
#   make search          -> one-shot vacancy search across all platforms
#   make search_linkedin -> one-shot LinkedIn search
#   make search_wellfound-> one-shot Wellfound search (needs make login_wellfound Chrome open)
```

- [ ] **Step 8: Run the full sender suite + import smoke**

Run: `sender/.venv/Scripts/python.exe -m pytest -q` (from `sender/`)
Expected: PASS (existing + 2 new).
Run: `sender/.venv/Scripts/python.exe -c "from app.interface.cli import run_search_once; from app.application.search_commands import platforms_arg; print('ok')"` (from `sender/`)
Expected: prints `ok`.

- [ ] **Step 9: Commit**

```bash
git add sender/app/application/search_commands.py sender/tests/test_search_commands.py sender/app/interface/cli.py sender/run.py Makefile
git commit -m "feat: one-shot make search / search_linkedin / search_wellfound"
```

---

### Task 3: Worker auto-search scheduler (~3×/day)

**Files:**
- Create: `sender/app/application/auto_search.py`
- Test: `sender/tests/test_auto_search.py`
- Modify: `sender/app/config.py:92` (add `SEARCH_EVERY_HOURS`)
- Modify: `sender/app/interface/cli.py` (`run_worker` loop)

**Interfaces:**
- Consumes: `datetime`; `config.SEARCH_EVERY_HOURS`; existing `run_one(req)` and `SearchRequest`.
- Produces: `should_auto_search(last_run, now, every_hours) -> bool`.

- [ ] **Step 1: Write the failing test** — create `sender/tests/test_auto_search.py`:

```python
import datetime as dt

from app.application.auto_search import should_auto_search


def test_runs_when_never_run_yet():
    now = dt.datetime(2026, 6, 20, 9, 0, 0)
    assert should_auto_search(None, now, every_hours=8) is True


def test_skips_before_interval_elapses():
    last = dt.datetime(2026, 6, 20, 9, 0, 0)
    now = last + dt.timedelta(hours=7, minutes=59)
    assert should_auto_search(last, now, every_hours=8) is False


def test_runs_after_interval_elapses():
    last = dt.datetime(2026, 6, 20, 9, 0, 0)
    now = last + dt.timedelta(hours=8)
    assert should_auto_search(last, now, every_hours=8) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest tests/test_auto_search.py -v` (from `sender/`)
Expected: FAIL — `ModuleNotFoundError: app.application.auto_search`.

- [ ] **Step 3: Write minimal implementation** — create `sender/app/application/auto_search.py`:

```python
"""Decide whether the worker should fire its periodic all-platform search."""


def should_auto_search(last_run, now, every_hours: int) -> bool:
    """True if no auto-search has run yet, or `every_hours` have elapsed."""
    if last_run is None:
        return True
    return (now - last_run).total_seconds() >= every_hours * 3600
```

- [ ] **Step 4: Run test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest tests/test_auto_search.py -v` (from `sender/`)
Expected: PASS (3).

- [ ] **Step 5: Add config** — in `sender/app/config.py`, after the `WORKER_POLL_SECONDS` / `HEARTBEAT_STALE_SECONDS` block (~line 91):

```python
# Worker fires an all-platform auto-search every N hours (8 ≈ 3×/day).
SEARCH_EVERY_HOURS = int(os.environ.get("SEARCH_EVERY_HOURS", "8"))
```

- [ ] **Step 6: Integrate into `run_worker`** — in `cli.py`, update the imports inside `run_worker` and its loop. Add to the existing `import time` line area:

```python
    import time
    from datetime import datetime

    from app.application.auto_search import should_auto_search
    from app.domain.search_request import SearchRequest
```

Replace the `while True:` loop with:

```python
    print("worker started; polling every", config.WORKER_POLL_SECONDS, "s")
    last_auto = None
    while True:
        try:
            worker_tick(control, run_one)
            now = datetime.now()
            if should_auto_search(last_auto, now, config.SEARCH_EVERY_HOURS):
                print("auto-search: all platforms")
                run_one(SearchRequest(id="auto", platform="all", status="running"))
                last_auto = now
        except Exception as exc:  # noqa: BLE001 — survive transient sheet errors
            print("tick error:", exc)
        time.sleep(config.WORKER_POLL_SECONDS)
```

(`SearchRequest` is the existing dataclass; `run_one` already calls `platforms_for(req.platform)`.)

- [ ] **Step 7: Run the full sender suite + worker import smoke**

Run: `sender/.venv/Scripts/python.exe -m pytest -q` (from `sender/`)
Expected: PASS.
Run: `sender/.venv/Scripts/python.exe -c "from app.interface.cli import run_worker; from app import config; print('every', config.SEARCH_EVERY_HOURS)"` (from `sender/`)
Expected: prints `every 8`.

- [ ] **Step 8: Commit**

```bash
git add sender/app/application/auto_search.py sender/tests/test_auto_search.py sender/app/config.py sender/app/interface/cli.py
git commit -m "feat: worker auto-searches all platforms every SEARCH_EVERY_HOURS"
```

---

### Task 4: Split Wellfound login (`make login_wellfound`, login-only)

**Files:**
- Modify: `sender/app/interface/cli.py` (rename `run_wellfound` → `run_login_wellfound`, drop the search pipeline, add a CDP sanity check)
- Modify: `sender/run.py` (dispatch `login_wellfound`)
- Modify: `Makefile` (rename `wellfound` → `login_wellfound`)

**Interfaces:**
- Consumes: `build_chrome_debug_args`, `config.CHROME_PATH/WELLFOUND_CHROME_PROFILE/WELLFOUND_CDP_PORT/WELLFOUND_CDP_URL`, `patchright`.
- Produces: `run_login_wellfound()` — launches the user's Chrome, leaves it running, verifies the session is past Cloudflare.

- [ ] **Step 1: Replace `run_wellfound` with `run_login_wellfound`** in `cli.py`:

```python
def run_login_wellfound():
    """Open the user's real Chrome for a one-time Wellfound login.

    Wellfound's Cloudflare loops on any browser we launch headless/automated, so
    the user passes Cloudflare + logs in by hand here. The Chrome is left RUNNING
    with a debug port; every Wellfound search (worker / make search*) attaches to
    it over CDP. Does not scrape — that is `make search_wellfound` / the worker.
    """
    import subprocess

    from app.infrastructure.search.wellfound_search import build_chrome_debug_args

    args = build_chrome_debug_args(
        config.WELLFOUND_CHROME_PROFILE, config.WELLFOUND_CDP_PORT,
        "https://wellfound.com/login")
    print("Открываю твой Chrome для Wellfound...")
    try:
        subprocess.Popen([config.CHROME_PATH, *args])
    except FileNotFoundError:
        print(f"❌ Не нашёл Chrome по пути {config.CHROME_PATH}. "
              f"Укажи его в переменной CHROME_PATH.")
        return

    print("\n1) Пройди проверку Cloudflare и залогинься в Wellfound в открывшемся Chrome.")
    print("2) Дождись, пока загрузится твоя лента (не страница «Один момент…»).")
    input("3) Потом вернись сюда и нажми Enter — проверю сессию...")

    try:
        from patchright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(config.WELLFOUND_CDP_URL)
            ctx = browser.contexts[0] if browser.contexts else None
            page = ctx.pages[0] if ctx and ctx.pages else None
            title = page.title() if page else ""
            browser.close()  # disconnect only — leaves Chrome running
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ Не смог проверить сессию по CDP: {exc}. Chrome всё равно оставь открытым.")
        return

    if "момент" in title.lower() or "moment" in title.lower():
        print("⚠️ Похоже, ещё на проверке Cloudflare. Доделай вход и запусти команду снова.")
    else:
        print("✅ Сессия готова. Chrome НЕ закрывай — поиск Wellfound пойдёт через него.")
```

Delete the old `run_wellfound` body entirely (the version that launched Chrome and then ran the search pipeline).

- [ ] **Step 2: Update `run.py` dispatch** — change the import and the wellfound branch:

```python
from app.interface.cli import (  # noqa: E402
    run,
    run_login_browser,
    run_login_wellfound,
    run_search_once,
    run_worker,
)
```

and replace the wellfound branch:

```python
    elif cmd == ["login_wellfound"]:
        run_login_wellfound()
```

- [ ] **Step 3: Rename the Makefile target** — change `wellfound:` to `login_wellfound:` running `sender/run.py login_wellfound`, update `.PHONY`, and update the comment line:

```makefile
#   make login_wellfound -> open your Chrome for a one-time Wellfound login (leave it open)
```

```makefile
login_wellfound:
	$(PYTHON) sender/run.py login_wellfound
```

- [ ] **Step 4: Run the full sender suite + import smoke**

Run: `sender/.venv/Scripts/python.exe -m pytest -q` (from `sender/`)
Expected: PASS.
Run: `sender/.venv/Scripts/python.exe -c "from app.interface.cli import run_login_wellfound; print('ok')"` (from `sender/`)
Expected: prints `ok`.
Run: `grep -n "run_wellfound" sender/run.py sender/app/interface/cli.py || echo "no stale refs"`
Expected: `no stale refs`.

- [ ] **Step 5: Commit**

```bash
git add sender/app/interface/cli.py sender/run.py Makefile
git commit -m "feat: make login_wellfound (login-only) replaces make wellfound"
```

---

### Task 5: Per-platform Telegram bot commands

**Files:**
- Create: `intake-bot/app/domain/bot_commands.py`
- Test: `intake-bot/tests/test_bot_commands.py`
- Modify: `intake-bot/api/webhook.py` (`_handle_command`, `/start` help text)

**Interfaces:**
- Consumes: nothing external (pure string mapping).
- Produces: `command_to_search_platform(text: str) -> str | None` returning `"all" | "linkedin" | "wellfound" | None`.

- [ ] **Step 1: Write the failing test** — create `intake-bot/tests/test_bot_commands.py`:

```python
from app.domain.bot_commands import command_to_search_platform


def test_start_search_means_all():
    assert command_to_search_platform("/start_search") == "all"


def test_per_platform_commands():
    assert command_to_search_platform("/search_linkedin") == "linkedin"
    assert command_to_search_platform("/search_wellfound") == "wellfound"


def test_non_search_command_returns_none():
    assert command_to_search_platform("/show_vacancies") is None
    assert command_to_search_platform("just some vacancy text") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest tests/test_bot_commands.py -v` (from `intake-bot/`)
Expected: FAIL — `ModuleNotFoundError: app.domain.bot_commands`.

- [ ] **Step 3: Write minimal implementation** — create `intake-bot/app/domain/bot_commands.py`:

```python
"""Map a Telegram command to the search platform it requests (or None)."""


def command_to_search_platform(text: str):
    t = text.strip()
    if t.startswith("/search_linkedin"):
        return "linkedin"
    if t.startswith("/search_wellfound"):
        return "wellfound"
    if t.startswith("/start_search"):
        return "all"
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest tests/test_bot_commands.py -v` (from `intake-bot/`)
Expected: PASS (3).

- [ ] **Step 5: Use it in `webhook.py`** — replace `_handle_command` and the `_do_start_search` queue call so any search command queues its platform. Change `_do_start_search` to accept a platform:

```python
def _do_start_search(chat_id: int, platform: str) -> None:
    from app.infrastructure.control_gateway import start_search_reply
    ctrl = _control_gateway()
    online = ctrl.is_worker_online(config.HEARTBEAT_STALE_SECONDS)
    ctrl.queue_search(platform)        # warn + queue regardless
    _reply(chat_id, start_search_reply(online))
```

and replace `_handle_command`:

```python
def _handle_command(text: str, chat_id: int) -> bool:
    from app.domain.bot_commands import command_to_search_platform
    platform = command_to_search_platform(text)
    if platform is not None:
        _do_start_search(chat_id, platform)
        return True
    if text.startswith("/show_vacancies"):
        _do_show_vacancies(chat_id)
        return True
    return False
```

- [ ] **Step 6: Update `/start` help text** — in `telegram_webhook`, change the help string:

```python
            "Привет! Кидай текст вакансии — я вытащу контакт и сохраню лид в таблицу.\n"
            "Команда /status — сводка по лидам (сколько new / sent).\n"
            "Поиск: /start_search — по всем платформам, /search_linkedin, "
            "/search_wellfound. /show_vacancies — показать найденные.",
```

- [ ] **Step 7: Run the intake-bot suite + import smoke**

Run: `sender/.venv/Scripts/python.exe -m pytest -q` (from `intake-bot/`)
Expected: PASS (existing + 3 new).
Run: `sender/.venv/Scripts/python.exe -c "import api.webhook; print('webhook import ok')"` (from `intake-bot/`)
Expected: prints `webhook import ok`.

- [ ] **Step 8: Commit**

```bash
git add intake-bot/app/domain/bot_commands.py intake-bot/tests/test_bot_commands.py intake-bot/api/webhook.py
git commit -m "feat: /search_linkedin and /search_wellfound bot commands"
```

---

### Task 6: Register the bot command menu (`make bot_menu`)

**Files:**
- Create: `sender/register_bot_menu.py`
- Test: `sender/tests/test_bot_menu.py`
- Modify: `Makefile` (`bot_menu` target)

**Interfaces:**
- Consumes: `TELEGRAM_BOT_TOKEN` from the root `.env`; `urllib`.
- Produces: `bot_commands_payload() -> list[dict]` (Telegram `setMyCommands` command objects).

- [ ] **Step 1: Write the failing test** — create `sender/tests/test_bot_menu.py`:

```python
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "register_bot_menu", Path(__file__).resolve().parents[1] / "register_bot_menu.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


def test_payload_lists_per_platform_search_commands():
    names = [c["command"] for c in _mod.bot_commands_payload()]
    assert "start_search" in names
    assert "search_linkedin" in names
    assert "search_wellfound" in names


def test_every_command_has_a_description():
    assert all(c.get("description") for c in _mod.bot_commands_payload())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest tests/test_bot_menu.py -v` (from `sender/`)
Expected: FAIL — `register_bot_menu.py` does not exist.

- [ ] **Step 3: Write minimal implementation** — create `sender/register_bot_menu.py`:

```python
"""Register the intake bot's command menu via Telegram setMyCommands.

Run once (and after changing commands): `make bot_menu`. Reads TELEGRAM_BOT_TOKEN
from the project-root .env.
"""
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def bot_commands_payload() -> list[dict]:
    return [
        {"command": "start_search", "description": "Искать вакансии по всем платформам"},
        {"command": "search_linkedin", "description": "Искать вакансии в LinkedIn"},
        {"command": "search_wellfound", "description": "Искать вакансии в Wellfound"},
        {"command": "show_vacancies", "description": "Показать найденные вакансии"},
        {"command": "status", "description": "Сводка по лидам (new / sent)"},
    ]


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("❌ TELEGRAM_BOT_TOKEN не задан в .env")
        return
    url = f"https://api.telegram.org/bot{token}/setMyCommands"
    data = urllib.parse.urlencode(
        {"commands": json.dumps(bot_commands_payload(), ensure_ascii=False)}).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10) as resp:
        print("setMyCommands:", resp.read().decode())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest tests/test_bot_menu.py -v` (from `sender/`)
Expected: PASS (2).

- [ ] **Step 5: Add Makefile target** — add `bot_menu` to `.PHONY`, a comment line, and:

```makefile
bot_menu:
	$(PYTHON) sender/register_bot_menu.py
```

```makefile
#   make bot_menu        -> register the bot's command menu in Telegram (one-time)
```

- [ ] **Step 6: Run the full sender suite**

Run: `sender/.venv/Scripts/python.exe -m pytest -q` (from `sender/`)
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add sender/register_bot_menu.py sender/tests/test_bot_menu.py Makefile
git commit -m "feat: make bot_menu registers Telegram command menu"
```

---

## Self-Review

**Spec coverage:**
- Worker auto-search (~3×/day) → Task 3. ✓
- One-shot Makefile triggers `search` / `search_linkedin` / `search_wellfound` → Task 2. ✓
- Per-platform bot commands `/search_linkedin` / `/search_wellfound` → Task 5. ✓
- `make bot_menu` (setMyCommands) → Task 6. ✓
- Rename `make wellfound` → `make login_wellfound` (login-only, warm Chrome) → Task 4. ✓
- Wellfound search via CDP everywhere → Task 1 (registry) + Task 2 (`run_search_once`) + Task 3 (worker uses the same `run_one`). ✓
- Config `SEARCH_EVERY_HOURS` → Task 3. ✓
- Tests for `should_auto_search`, `platforms_arg`, `command_to_search_platform`, `bot_commands_payload` → Tasks 3, 2, 5, 6. ✓

**Placeholder scan:** No TBD/TODO; every code step shows full code. ✓

**Type consistency:** `platforms_arg(token) -> list[str]`, `run_search_once(platforms)`, `should_auto_search(last_run, now, every_hours)`, `command_to_search_platform(text) -> str|None`, `bot_commands_payload() -> list[dict]` are used identically wherever referenced. `run.py`'s import list is set in Task 2 and finalized in Task 4 (note called out in Task 2 Step 6). ✓

**Ordering note:** Tasks 1–4 (sender) then 5 (intake-bot) then 6 (sender). Task 2's `run.py` still imports `run_wellfound`; Task 4 renames it to `run_login_wellfound` and updates the import + dispatch. Between Tasks 2 and 4 `run.py` remains valid (it imports the still-existing `run_wellfound`).
