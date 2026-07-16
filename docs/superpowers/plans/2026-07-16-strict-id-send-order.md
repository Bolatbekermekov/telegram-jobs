# Strict id-order send loop — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `make run` process `new` leads in strict sheet order (by id, top-to-bottom) instead of grouping them by platform, while keeping the "one channel open at a time" invariant.

**Architecture:** A new `ChannelSwitcher` holds at most one started channel and lazily switches (close current → open next) only when the platform changes between consecutive leads. `run()` walks `leads` in the order `fetch_new_leads()` returns them (already id/row order). A pure `skip_reason()` decides per-lead whether to skip (unknown platform / channel-failed / rate-limited / daily-limit) **before** any channel is opened, so skipped leads never churn channels. The old `group_leads_by_platform()` batching is removed.

**Tech Stack:** Python 3, pytest, gspread (Google Sheets), Telethon (Telegram), Playwright (LinkedIn/HH/Wellfound). Unchanged.

## Global Constraints

- **Single-open-channel invariant:** never have two channels started at once — Telethon (asyncio) and Playwright cannot be live in the same process simultaneously. Switching = stop current, then start next.
- **Preserve every existing per-lead behavior:** statuses `sent`/`invited`/`manual`/`failed`/`skipped`; per-platform cap `config.DAILY_SEND_LIMIT`; anti-ban pause `random.randint(config.MIN_DELAY_SECONDS, config.MAX_DELAY_SECONDS)` after each successful send/invite; manual-mode `[s]end / [k]skip / [q]uit` prompt; the `[плейсхолдер]` warning.
- **Offline tests:** `make test-unit` == `pytest sender/tests -v -m "not live"`. New unit tests must not touch the network or real channels.
- **Env:** Windows / PowerShell. Interpreter: `sender/.venv/Scripts/python.exe`. Run pytest from the project root.
- **Secrets:** never commit `sender/apply_profile.yml`, `.env`, `service_account.json`, CV. (No task here touches them.)

---

### Task 1: `ChannelSwitcher` — single open channel, lazy switching

**Files:**
- Create: `sender/app/application/channel_switcher.py`
- Test: `sender/tests/test_channel_switcher.py`

**Interfaces:**
- Consumes: nothing (pure orchestration; the channel factory is injected).
- Produces:
  - `ChannelSwitcher(build)` where `build(platform: str) -> channel` returns a **fresh, not-yet-started** channel exposing `.start()` and `.stop()`.
  - `.for_platform(platform: str) -> channel` — returns a **started** channel for `platform`; if a channel for a different platform is open, stops it and starts a fresh one; if the same platform is already open, returns it unchanged (no restart). Propagates any exception from `.start()` and leaves the switcher holding nothing.
  - `.close() -> None` — stops the open channel if any (swallowing `.stop()` errors) and resets to empty; safe to call when nothing is open and safe to call twice.

- [ ] **Step 1: Write the failing tests**

Create `sender/tests/test_channel_switcher.py`:

```python
import pytest

from app.application.channel_switcher import ChannelSwitcher


class FakeChannel:
    def __init__(self, platform, log, raise_on_start=False, raise_on_stop=False):
        self.platform = platform
        self._log = log
        self._raise_on_start = raise_on_start
        self._raise_on_stop = raise_on_stop

    def start(self):
        if self._raise_on_start:
            raise RuntimeError(f"cannot start {self.platform}")
        self._log.append(("start", self.platform))

    def stop(self):
        if self._raise_on_stop:
            raise RuntimeError(f"stop boom {self.platform}")
        self._log.append(("stop", self.platform))


def _switcher(raise_start=(), raise_stop=()):
    log = []

    def build(platform):
        return FakeChannel(platform, log,
                           raise_on_start=platform in raise_start,
                           raise_on_stop=platform in raise_stop)

    return ChannelSwitcher(build), log


def test_first_platform_opens_and_starts_channel():
    sw, log = _switcher()
    ch = sw.for_platform("telegram")
    assert ch.platform == "telegram"
    assert log == [("start", "telegram")]


def test_same_platform_reuses_open_channel_without_restart():
    sw, log = _switcher()
    a = sw.for_platform("telegram")
    b = sw.for_platform("telegram")
    assert a is b
    assert log == [("start", "telegram")]


def test_switching_platform_stops_previous_then_starts_new():
    sw, log = _switcher()
    sw.for_platform("telegram")
    sw.for_platform("linkedin")
    assert log == [("start", "telegram"), ("stop", "telegram"), ("start", "linkedin")]


def test_reopening_same_platform_after_switch_builds_fresh():
    sw, log = _switcher()
    sw.for_platform("telegram")
    sw.for_platform("linkedin")
    sw.for_platform("telegram")
    assert log == [
        ("start", "telegram"), ("stop", "telegram"),
        ("start", "linkedin"), ("stop", "linkedin"),
        ("start", "telegram"),
    ]


def test_close_stops_open_channel_and_is_idempotent():
    sw, log = _switcher()
    sw.for_platform("telegram")
    sw.close()
    sw.close()
    assert log == [("start", "telegram"), ("stop", "telegram")]


def test_close_without_open_channel_is_noop():
    sw, log = _switcher()
    sw.close()
    assert log == []


def test_start_failure_propagates_and_leaves_switcher_empty():
    sw, log = _switcher(raise_start=("linkedin",))
    sw.for_platform("telegram")
    with pytest.raises(RuntimeError, match="cannot start linkedin"):
        sw.for_platform("linkedin")
    assert log == [("start", "telegram"), ("stop", "telegram")]
    sw.for_platform("hh")           # switcher is usable again, no stale state
    assert log[-1] == ("start", "hh")


def test_close_swallows_stop_errors():
    sw, log = _switcher(raise_stop=("telegram",))
    sw.for_platform("telegram")
    sw.close()                      # must not raise even though stop() throws
    sw.for_platform("hh")
    assert ("start", "hh") in log
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_channel_switcher.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.application.channel_switcher'`.

- [ ] **Step 3: Write the minimal implementation**

Create `sender/app/application/channel_switcher.py`:

```python
"""Keeps at most one outreach channel open at a time.

Telethon (Telegram) and Playwright (LinkedIn/HH/Wellfound) cannot run in the
same process simultaneously, so while processing leads in id order we hold a
single open channel and switch lazily as the platform changes. A fresh channel
is built on every (re)open — stopped channels are never reused.
"""


class ChannelSwitcher:
    def __init__(self, build):
        """`build(platform) -> channel` returns a fresh, not-yet-started channel."""
        self._build = build
        self._channel = None
        self._platform = None

    def for_platform(self, platform):
        """Return a started channel for `platform`, switching if a different one
        is open. Reuses the open channel when the platform already matches."""
        if self._platform != platform:
            self.close()
            channel = self._build(platform)
            channel.start()                 # may raise -> switcher stays empty
            self._channel = channel
            self._platform = platform
        return self._channel

    def close(self):
        """Stop the open channel, if any. Never raises."""
        if self._channel is not None:
            try:
                self._channel.stop()
            except Exception:  # noqa: BLE001 — a broken stop must not abort the run
                pass
            self._channel = None
            self._platform = None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_channel_switcher.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add sender/app/application/channel_switcher.py sender/tests/test_channel_switcher.py
git commit -m "feat(send): ChannelSwitcher — one open channel, lazy platform switch"
```

---

### Task 2: `skip_reason` — per-lead gating before any channel opens

**Files:**
- Modify: `sender/app/application/send_plan.py` (add `skip_reason`; keep `group_leads_by_platform` for now)
- Test: `sender/tests/test_send_plan.py` (add `skip_reason` tests alongside the existing group tests)

**Interfaces:**
- Consumes: `STATUS_SKIPPED`, `STATUS_FAILED` from `app.domain.lead`; a `lead` with a `.platform` attribute.
- Produces:
  - `skip_reason(lead, known, sent_per_platform, daily_limit, rate_limited, failed_platforms) -> tuple[str, str] | None`
  - Returns `(status, note)` to skip, or `None` to proceed. Precedence: unknown platform → channel-failed → rate-limited → daily-limit reached.

- [ ] **Step 1: Write the failing tests**

Add to `sender/tests/test_send_plan.py` (keep the existing imports and tests; append this):

```python
from app.application.send_plan import skip_reason
from app.domain.lead import STATUS_FAILED, STATUS_SKIPPED

_KNOWN_T = {"telegram", "linkedin", "hh"}


def _lead(platform):
    return _Lead(0, platform)   # _Lead is defined at the top of this file


def test_skip_unknown_platform():
    assert skip_reason(_lead("myspace"), _KNOWN_T, {}, 10, set(), set()) == (
        STATUS_SKIPPED, "unknown platform: myspace")


def test_skip_platform_whose_channel_failed():
    assert skip_reason(_lead("linkedin"), _KNOWN_T, {}, 10, set(), {"linkedin"}) == (
        STATUS_FAILED, "channel start failed earlier this run")


def test_skip_rate_limited_platform():
    assert skip_reason(_lead("hh"), _KNOWN_T, {}, 10, {"hh"}, set()) == (
        STATUS_SKIPPED, "rate-limited earlier this run")


def test_skip_when_daily_limit_reached():
    assert skip_reason(_lead("telegram"), _KNOWN_T, {"telegram": 10}, 10, set(), set()) == (
        STATUS_SKIPPED, "daily limit reached")


def test_no_skip_when_healthy_and_under_limit():
    assert skip_reason(_lead("telegram"), _KNOWN_T, {"telegram": 3}, 10, set(), set()) is None


def test_unknown_takes_precedence_over_failed():
    assert skip_reason(_lead("x"), _KNOWN_T, {}, 10, set(), {"x"}) == (
        STATUS_SKIPPED, "unknown platform: x")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_send_plan.py -v`
Expected: FAIL — `ImportError: cannot import name 'skip_reason'`.

- [ ] **Step 3: Write the minimal implementation**

Add to `sender/app/application/send_plan.py` (below the existing `group_leads_by_platform`, and add the import at the top of the file):

```python
from app.domain.lead import STATUS_FAILED, STATUS_SKIPPED


def skip_reason(lead, known, sent_per_platform, daily_limit,
                rate_limited, failed_platforms):
    """Why this lead can't be sent right now, as (status, note), or None to send.

    Checked before any channel opens, so a skip never triggers a channel switch.
    Order: unknown platform, then a platform whose channel already failed this
    run, then one that rate-limited us, then the per-platform daily cap.
    """
    p = lead.platform
    if p not in known:
        return (STATUS_SKIPPED, f"unknown platform: {p}")
    if p in failed_platforms:
        return (STATUS_FAILED, "channel start failed earlier this run")
    if p in rate_limited:
        return (STATUS_SKIPPED, "rate-limited earlier this run")
    if sent_per_platform.get(p, 0) >= daily_limit:
        return (STATUS_SKIPPED, "daily limit reached")
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_send_plan.py -v`
Expected: PASS (existing group tests + 6 new `skip_reason` tests).

- [ ] **Step 5: Commit**

```bash
git add sender/app/application/send_plan.py sender/tests/test_send_plan.py
git commit -m "feat(send): skip_reason — per-lead gating for id-order loop"
```

---

### Task 3: Rewrite `run()` to strict id order using ChannelSwitcher + skip_reason

**Files:**
- Modify: `sender/app/interface/cli.py` (module docstring lines 1–7; import line 15; the send loop lines 85–181)

**Interfaces:**
- Consumes: `ChannelSwitcher` (Task 1), `skip_reason` (Task 2), existing `build_channel`, `SendOutreach`, `subject_for`, `format_for_channel`, `_show`, `_prompt`, `_KNOWN`, and the `STATUS_*` constants already imported in this file.
- Produces: no new public symbols; `run()` keeps its signature `run() -> None`.

- [ ] **Step 1: Update the module docstring**

Replace lines 1–7 of `sender/app/interface/cli.py`:

```python
"""Interactive CLI: read `new` leads, generate, approve, send across platforms.

Leads are processed in sheet order (by id, top to bottom). At most one channel
is open at a time — browser channels and the Telegram userbot can't share a
process — so ChannelSwitcher stops the current channel and starts the next
whenever the platform changes between consecutive leads. Default mode asks
send/edit/skip per lead; AUTO_SEND=true sends automatically. Per-platform daily
limits and anti-ban delays apply.
"""
```

- [ ] **Step 2: Swap the import**

Replace line 15 `from app.application.send_plan import group_leads_by_platform` with:

```python
from app.application.channel_switcher import ChannelSwitcher
from app.application.send_plan import skip_reason
```

- [ ] **Step 3: Replace the send loop**

Replace the block from line 85 (`sent_per_platform: dict[str, int] = {}`) through line 181 (the final `print(f"\nГотово. ...")`) with:

```python
    sent_per_platform: dict[str, int] = {}
    rate_limited: set[str] = set()       # platforms that rate-limited us this run
    failed_platforms: set[str] = set()   # platforms whose channel failed to start
    quit_requested = False

    # Strict id order: walk leads top-to-bottom. ChannelSwitcher keeps a single
    # channel open and switches only when the platform changes (Telethon and
    # Playwright can't be live at once). skip_reason() runs before any channel
    # opens, so skipped leads never churn channels.
    switcher = ChannelSwitcher(lambda p: build_channel(p, config))
    try:
        for lead in leads:
            if quit_requested:
                break
            platform = lead.platform

            reason = skip_reason(lead, _KNOWN, sent_per_platform,
                                 config.DAILY_SEND_LIMIT, rate_limited, failed_platforms)
            if reason is not None:
                status, note = reason
                repo.mark_status(lead, status, note=note)
                print(f"⏭  Лид #{lead.lead_id} [{platform}]: {note} — пропуск.")
                continue

            try:
                channel = switcher.for_platform(platform)
            except Exception as exc:  # noqa: BLE001
                repo.mark_status(lead, STATUS_FAILED, note=f"channel start failed: {exc}")
                failed_platforms.add(platform)
                print(f"❌ Не удалось поднять канал '{platform}': {exc} — пропускаю его лиды.")
                continue
            sender = SendOutreach(channel)

            print("\n" + "=" * 60)
            print(f"Лид #{lead.lead_id}  [{platform}]  →  {lead.target}")
            print(f"Вакансия: {lead.vacancy_context or lead.raw_text}")
            print("-" * 60)

            print("Генерирую сообщение...")
            body = generator.execute(lead)
            subject = subject_for(lead.vacancy_context or lead.raw_text)
            attachment = config.CV_PATH if config.ATTACH_CV else None
            content = format_for_channel(channel, body, subject, attachment)

            if not config.AUTO_SEND:
                _show(content.body)
                if "[" in content.body:
                    print("⚠️  Остался [плейсхолдер] — заполни через edit перед отправкой.")
                choice = _prompt("[s]end / [k]skip / [q]uit: ").lower()
                if choice in ("k", "skip"):
                    repo.mark_status(lead, STATUS_SKIPPED)
                    print("⏭  Пропущено.")
                    continue
                if choice in ("q", "quit"):
                    print("Выход по запросу.")
                    quit_requested = True
                    break

            result = sender.execute(lead, content)
            if result.ok:
                repo.mark_sent(lead, content.body, STATUS_SENT)
                sent_per_platform[platform] = sent_per_platform.get(platform, 0) + 1
                print(f"✅ Отправлено [{platform}] "
                      f"({sent_per_platform[platform]}/{config.DAILY_SEND_LIMIT}).")
                delay = random.randint(config.MIN_DELAY_SECONDS, config.MAX_DELAY_SECONDS)
                print(f"⏳ Пауза {delay} c (анти-бан)...")
                time.sleep(delay)
            elif result.invited:
                # Connection request with a note was sent — a real outreach
                # action (counts toward the limit); CV goes after acceptance.
                repo.mark_status(lead, STATUS_INVITED, note=result.error)
                sent_per_platform[platform] = sent_per_platform.get(platform, 0) + 1
                print(f"📨 Запрос на контакт отправлен [{platform}] "
                      f"({sent_per_platform[platform]}/{config.DAILY_SEND_LIMIT}). "
                      "CV — после подтверждения.")
                delay = random.randint(config.MIN_DELAY_SECONDS, config.MAX_DELAY_SECONDS)
                print(f"⏳ Пауза {delay} c (анти-бан)...")
                time.sleep(delay)
            elif result.manual:
                # Couldn't auto-apply (gate/unknown form); leave for a manual apply.
                repo.mark_status(lead, STATUS_MANUAL, note=result.error)
                print(f"✋ Нужен ручной отклик [{platform}]: {result.error}")
            elif result.rate_limited:
                repo.mark_status(lead, STATUS_SKIPPED, note="rate-limited")
                rate_limited.add(platform)
                print(f"🛑 Платформа '{platform}' ограничила нас — "
                      "пропускаю её остальные лиды на этот запуск.")
            else:
                repo.mark_status(lead, STATUS_FAILED, note=result.error)
                print(f"❌ Ошибка отправки: {result.error}")
    finally:
        switcher.close()

    total = sum(sent_per_platform.values())
    print(f"\nГотово. Отправлено за сессию: {total}. По платформам: {sent_per_platform}")
```

- [ ] **Step 4: Verify the module imports and the whole suite is green**

Run: `sender/.venv/Scripts/python.exe -c "import app.interface.cli"`
Expected: no output, exit 0 (no import errors; `group_leads_by_platform` is no longer referenced here).

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests -v -m "not live"`
Expected: PASS — full suite green (≥ 247 + the new tests). `test_send_plan.py` still passes because `group_leads_by_platform` still exists (removed in Task 4).

- [ ] **Step 5: Commit**

```bash
git add sender/app/interface/cli.py
git commit -m "feat(send): process leads in strict id order via ChannelSwitcher"
```

---

### Task 4: Remove the now-dead `group_leads_by_platform`

**Files:**
- Modify: `sender/app/application/send_plan.py` (delete `group_leads_by_platform` + its docstring paragraph; keep `skip_reason`)
- Modify: `sender/tests/test_send_plan.py` (delete the three `group_leads_by_platform` tests and the `_Lead`-based grouping imports; keep the `skip_reason` tests)

**Interfaces:**
- Consumes: nothing new.
- Produces: `send_plan.py` now exposes only `skip_reason`.

- [ ] **Step 1: Confirm nothing else imports the function**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests -q -k "group_leads_by_platform"` then grep.
Run: `grep -rn "group_leads_by_platform" sender/app sender/tests`
Expected: matches ONLY in `send_plan.py` (definition) and `test_send_plan.py` (its tests). If anything else appears, stop and reconcile.

- [ ] **Step 2: Rewrite `send_plan.py` to keep only `skip_reason`**

Replace the entire contents of `sender/app/application/send_plan.py` with:

```python
"""Per-lead gating for the id-order send loop.

Leads are sent in sheet order (by id). Before opening a channel for a lead we
ask skip_reason() whether it should be skipped (unknown platform, a channel that
already failed this run, a platform that rate-limited us, or the per-platform
daily cap) — so a skip never causes a channel switch.
"""
from app.domain.lead import STATUS_FAILED, STATUS_SKIPPED


def skip_reason(lead, known, sent_per_platform, daily_limit,
                rate_limited, failed_platforms):
    """Why this lead can't be sent right now, as (status, note), or None to send.

    Order: unknown platform, then a platform whose channel already failed this
    run, then one that rate-limited us, then the per-platform daily cap.
    """
    p = lead.platform
    if p not in known:
        return (STATUS_SKIPPED, f"unknown platform: {p}")
    if p in failed_platforms:
        return (STATUS_FAILED, "channel start failed earlier this run")
    if p in rate_limited:
        return (STATUS_SKIPPED, "rate-limited earlier this run")
    if sent_per_platform.get(p, 0) >= daily_limit:
        return (STATUS_SKIPPED, "daily limit reached")
    return None
```

- [ ] **Step 3: Trim `test_send_plan.py` to the `skip_reason` tests only**

Replace the entire contents of `sender/tests/test_send_plan.py` with:

```python
from app.application.send_plan import skip_reason
from app.domain.lead import STATUS_FAILED, STATUS_SKIPPED

_KNOWN_T = {"telegram", "linkedin", "hh"}


class _Lead:
    def __init__(self, platform):
        self.platform = platform


def test_skip_unknown_platform():
    assert skip_reason(_Lead("myspace"), _KNOWN_T, {}, 10, set(), set()) == (
        STATUS_SKIPPED, "unknown platform: myspace")


def test_skip_platform_whose_channel_failed():
    assert skip_reason(_Lead("linkedin"), _KNOWN_T, {}, 10, set(), {"linkedin"}) == (
        STATUS_FAILED, "channel start failed earlier this run")


def test_skip_rate_limited_platform():
    assert skip_reason(_Lead("hh"), _KNOWN_T, {}, 10, {"hh"}, set()) == (
        STATUS_SKIPPED, "rate-limited earlier this run")


def test_skip_when_daily_limit_reached():
    assert skip_reason(_Lead("telegram"), _KNOWN_T, {"telegram": 10}, 10, set(), set()) == (
        STATUS_SKIPPED, "daily limit reached")


def test_no_skip_when_healthy_and_under_limit():
    assert skip_reason(_Lead("telegram"), _KNOWN_T, {"telegram": 3}, 10, set(), set()) is None


def test_unknown_takes_precedence_over_failed():
    assert skip_reason(_Lead("x"), _KNOWN_T, {}, 10, set(), {"x"}) == (
        STATUS_SKIPPED, "unknown platform: x")
```

- [ ] **Step 4: Run the suite**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests -v -m "not live"`
Expected: PASS — full suite green; `test_send_plan.py` now runs only the 6 `skip_reason` tests.

- [ ] **Step 5: Commit**

```bash
git add sender/app/application/send_plan.py sender/tests/test_send_plan.py
git commit -m "refactor(send): drop group_leads_by_platform (superseded by id order)"
```

---

### Task 5: Live smoke verification (manual — run by the user)

**Purpose:** ChannelSwitcher's reopen path (a second Telethon client + repeated `sync_playwright().start()/stop()` in one process) is only truly proven against real channels. The unit tests prove the switch *sequence*; this proves the switch *works live*.

**Precondition:** a few `new` leads in the sheet whose platforms **interleave** (e.g. rows id 1 telegram, 2 linkedin, 3 telegram) so a real reopen happens. Sessions logged in (`make login`). No secrets committed.

- [ ] **Step 1:** Set manual mode so nothing sends unless you approve: ensure `AUTO_SEND` is not `true` in `.env`.
- [ ] **Step 2:** Run `make run`.
- [ ] **Step 3:** Watch the console order. Confirm leads are offered **in id order** (1, 2, 3 …), not grouped. Press `k` (skip) at each `[s]/[k]/[q]` prompt so nothing is actually sent.
- [ ] **Step 4:** Confirm the channel lifecycle in the logs: telegram opens for id 1 → closes → linkedin opens for id 2 → closes → **telegram opens again** for id 3 (the reopen). No `asyncio`/greenlet/`database is locked` errors.
- [ ] **Step 5:** If the Telethon reopen or the Playwright restart errors out, capture the traceback — the fix is a follow-up (e.g. reuse a cached-but-stopped Telegram client, or force a fresh event loop). Note it; do not force-flip `AUTO_SEND`.

---

## Self-Review

**Spec coverage:**
- Strict id order → Task 3 (loop over `leads` as returned, no grouping). ✓
- Single-open-channel invariant → Task 1 `ChannelSwitcher`. ✓
- Skips don't churn channels → Task 2 `skip_reason` called before `for_platform`. ✓
- Preserve statuses / daily cap / anti-ban delay / manual prompt → Task 3 keeps every branch verbatim. ✓
- rate-limit "skip the rest of this platform" (was `break` on a contiguous group) → Task 3 adds platform to `rate_limited`; future leads gated by `skip_reason`. ✓
- channel-start failure "skip this platform's leads" (was mark-whole-group) → Task 3 adds to `failed_platforms`; future leads gated. ✓
- Remove dead grouping code → Task 4. ✓
- Live proof of reopen → Task 5. ✓

**Placeholder scan:** none — every code step is complete.

**Type consistency:** `ChannelSwitcher(build)`, `.for_platform(platform)`, `.close()` used identically in Task 1 and Task 3. `skip_reason(lead, known, sent_per_platform, daily_limit, rate_limited, failed_platforms) -> (status, note) | None` identical in Tasks 2, 3, 4. `sent_per_platform` is `dict[str,int]`; `rate_limited`/`failed_platforms` are `set[str]` throughout.

**Ordering safety:** each task ends with a green suite — `group_leads_by_platform` survives until Task 3 stops using it and is deleted only in Task 4.
