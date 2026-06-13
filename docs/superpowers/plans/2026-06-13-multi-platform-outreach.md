# Multi-Platform Outreach Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generalize the sender so a single run delivers outreach across Telegram, LinkedIn, HeadHunter, Email and Wellfound, choosing the channel per lead from a "Платформа" column.

**Architecture:** Ports & adapters. A single `OutreachChannel` protocol abstracts every platform; each platform is an adapter under `sender/app/infrastructure/channels/`. The `SendOutreach` use-case stays platform-agnostic and works with an `OutreachContent` value object. A registry maps a platform string to a lazily-built channel. Browser (Playwright) and API (httpx/smtplib) logic is split into pure, mockable functions so unit tests never launch a real browser or network call.

**Tech Stack:** Python 3.11+, Telethon (existing), Playwright (new), httpx (new), smtplib (stdlib), gspread, OpenAI, pytest (new, dev-only).

---

## File Structure

**New files:**
- `sender/requirements-dev.txt` — pytest for the test suite.
- `sender/tests/__init__.py`, `sender/tests/conftest.py` — make `app` importable from tests.
- `sender/app/domain/channel.py` — `OutreachContent`, `OutreachChannel` protocol, `ChannelError`, `RateLimitedError`.
- `sender/app/application/format_content.py` — `format_for_channel(channel, body, subject)` → `OutreachContent`.
- `sender/app/infrastructure/channels/__init__.py`
- `sender/app/infrastructure/channels/telegram.py` — Telethon adapter (moved from `telethon_client.py`).
- `sender/app/infrastructure/channels/email_channel.py` — SMTP adapter + pure `build_email`.
- `sender/app/infrastructure/channels/headhunter.py` — hh.ru API adapter + pure `post_negotiation`.
- `sender/app/infrastructure/channels/linkedin.py` — Playwright adapter + pure `fill_and_send`.
- `sender/app/infrastructure/channels/wellfound.py` — Playwright adapter + pure `apply_via_page`.
- `sender/app/infrastructure/channels/registry.py` — `build_channel`, `enabled_platforms`.
- Test files mirroring each unit under `sender/tests/`.

**Modified files:**
- `sender/app/domain/lead.py` — add `platform`/`target`, add columns.
- `sender/app/application/send_outreach.py` — work with `OutreachChannel` + `OutreachContent`.
- `sender/app/infrastructure/sheets_repo.py` — read new columns.
- `sender/app/interface/cli.py` — group by platform, lazy channel start, per-platform limits.
- `sender/app/config.py` — per-platform config blocks.
- `sender/requirements.txt` — add `playwright`, `httpx`.
- `sender/test_send.py` — adapt to new `Lead`/`SendOutreach` API.
- `.env.example`, `Makefile`, `README.md` — document new platforms.

**Note on `platform` values (used everywhere):** `"telegram"`, `"linkedin"`, `"hh"`, `"email"`, `"wellfound"`.

---

## Task 1: Test infrastructure (pytest)

**Files:**
- Create: `sender/requirements-dev.txt`
- Create: `sender/tests/__init__.py`
- Create: `sender/tests/conftest.py`
- Create: `sender/tests/test_smoke.py`

- [ ] **Step 1: Create dev requirements**

`sender/requirements-dev.txt`:
```
pytest==8.3.4
```

- [ ] **Step 2: Install pytest into the existing venv**

Run: `sender/.venv/Scripts/python.exe -m pip install -r sender/requirements-dev.txt`
Expected: `Successfully installed pytest-8.3.4 ...`

- [ ] **Step 3: Make `app` importable from tests**

`sender/tests/__init__.py`: empty file.

`sender/tests/conftest.py`:
```python
"""Put the sender package root on sys.path so `import app...` works in tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
```

- [ ] **Step 4: Write a smoke test**

`sender/tests/test_smoke.py`:
```python
def test_pytest_runs():
    assert True
```

- [ ] **Step 5: Run the smoke test**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_smoke.py -v`
Expected: `1 passed`.

- [ ] **Step 6: Commit**

```bash
git add sender/requirements-dev.txt sender/tests/
git commit -m "test: add pytest infrastructure for sender"
```

---

## Task 2: Domain — channel port and content value object

**Files:**
- Create: `sender/app/domain/channel.py`
- Test: `sender/tests/test_channel_domain.py`

- [ ] **Step 1: Write the failing test**

`sender/tests/test_channel_domain.py`:
```python
from app.domain.channel import (
    ChannelError,
    OutreachContent,
    RateLimitedError,
)


def test_content_defaults():
    c = OutreachContent(body="hi")
    assert c.body == "hi"
    assert c.subject is None
    assert c.attachment_path is None


def test_rate_limited_is_channel_error():
    assert issubclass(RateLimitedError, ChannelError)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_channel_domain.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.domain.channel'`.

- [ ] **Step 3: Write the implementation**

`sender/app/domain/channel.py`:
```python
"""Outreach channel port: the single interface every platform adapter implements."""
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class ChannelError(Exception):
    """A send failed for a reason specific to one lead (bad target, transport error)."""


class RateLimitedError(ChannelError):
    """The platform throttled/blocked us. The caller should stop THIS platform."""


@dataclass
class OutreachContent:
    body: str
    subject: str | None = None        # used by channels with needs_subject (email)
    attachment_path: str | None = None


@runtime_checkable
class OutreachChannel(Protocol):
    name: str                  # one of: telegram | linkedin | hh | email | wellfound
    body_limit: int | None     # max chars for body (LinkedIn note = 300); None = unlimited
    needs_subject: bool        # True => a subject must be generated (email)

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def send(self, target: str, content: OutreachContent) -> None: ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_channel_domain.py -v`
Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add sender/app/domain/channel.py sender/tests/test_channel_domain.py
git commit -m "feat: add OutreachChannel port and OutreachContent value object"
```

---

## Task 3: Domain — Lead gains platform/target, columns updated

**Files:**
- Modify: `sender/app/domain/lead.py`
- Test: `sender/tests/test_lead_domain.py`

- [ ] **Step 1: Write the failing test**

`sender/tests/test_lead_domain.py`:
```python
from app.domain.lead import COLUMNS, Lead


def test_columns_include_platform_and_target():
    assert "Платформа" in COLUMNS
    assert "Цель" in COLUMNS


def test_lead_has_platform_and_target():
    lead = Lead(
        row=2, lead_id="1", platform="telegram", target="@nick",
        vacancy_context="Backend", raw_text="raw", status="new",
    )
    assert lead.platform == "telegram"
    assert lead.target == "@nick"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_lead_domain.py -v`
Expected: FAIL (`"Платформа" not in COLUMNS` / `Lead` has no `platform`).

- [ ] **Step 3: Edit `sender/app/domain/lead.py`**

Replace the whole file with:
```python
"""Domain entities for the sender. No external dependencies."""
from dataclasses import dataclass

# Fixed column order of the Google Sheet (must match the intake bot).
COLUMNS = [
    "id",
    "Дата добавления",
    "Исходный текст",
    "Платформа",
    "Цель",
    "Вакансия",
    "Сообщение",
    "Статус",
    "Дата отправки",
    "Заметка",
]

# 1-based column indexes used for targeted cell updates.
COL_MESSAGE = COLUMNS.index("Сообщение") + 1
COL_STATUS = COLUMNS.index("Статус") + 1
COL_DATE_SENT = COLUMNS.index("Дата отправки") + 1
COL_NOTE = COLUMNS.index("Заметка") + 1

STATUS_NEW = "new"
STATUS_SENT = "sent"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"

# Default platform when the "Платформа" cell is empty (back-compat with old rows).
DEFAULT_PLATFORM = "telegram"


@dataclass
class Lead:
    row: int               # 1-based row number in the sheet (incl. header offset)
    lead_id: str
    platform: str          # telegram | linkedin | hh | email | wellfound
    target: str            # @nick / profile URL / vacancy URL / email
    vacancy_context: str
    raw_text: str
    status: str
```

- [ ] **Step 4: Run test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_lead_domain.py -v`
Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add sender/app/domain/lead.py sender/tests/test_lead_domain.py
git commit -m "feat: add platform/target to Lead and sheet columns"
```

---

## Task 4: Refactor SendOutreach to channel + content

**Files:**
- Modify: `sender/app/application/send_outreach.py`
- Test: `sender/tests/test_send_outreach.py`

- [ ] **Step 1: Write the failing test**

`sender/tests/test_send_outreach.py`:
```python
from app.application.send_outreach import SendOutreach
from app.domain.channel import OutreachContent, RateLimitedError
from app.domain.lead import Lead


class _FakeChannel:
    name = "fake"
    body_limit = None
    needs_subject = False

    def __init__(self, raise_exc=None):
        self.sent = []
        self._raise = raise_exc

    def start(self): ...
    def stop(self): ...

    def send(self, target, content):
        if self._raise:
            raise self._raise
        self.sent.append((target, content))


def _lead():
    return Lead(row=2, lead_id="1", platform="fake", target="@x",
                vacancy_context="v", raw_text="r", status="new")


def test_sends_content_to_target():
    ch = _FakeChannel()
    result = SendOutreach(ch).execute(_lead(), OutreachContent(body="hello"))
    assert result.ok
    assert ch.sent == [("@x", OutreachContent(body="hello"))]


def test_captures_error():
    ch = _FakeChannel(raise_exc=ValueError("boom"))
    result = SendOutreach(ch).execute(_lead(), OutreachContent(body="hi"))
    assert not result.ok
    assert "boom" in result.error
    assert result.rate_limited is False


def test_flags_rate_limit():
    ch = _FakeChannel(raise_exc=RateLimitedError("blocked"))
    result = SendOutreach(ch).execute(_lead(), OutreachContent(body="hi"))
    assert not result.ok
    assert result.rate_limited is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_send_outreach.py -v`
Expected: FAIL (`SendOutreach.__init__` still expects `messenger, cv_path, attach_cv`; no `rate_limited`).

- [ ] **Step 3: Replace `sender/app/application/send_outreach.py`**

```python
"""Use-case: send one outreach message to a lead and report the result."""
from dataclasses import dataclass

from app.domain.channel import OutreachChannel, OutreachContent, RateLimitedError
from app.domain.lead import Lead


@dataclass
class SendResult:
    ok: bool
    error: str = ""
    rate_limited: bool = False


class SendOutreach:
    def __init__(self, channel: OutreachChannel):
        self._channel = channel

    def execute(self, lead: Lead, content: OutreachContent) -> SendResult:
        try:
            self._channel.send(lead.target, content)
            return SendResult(ok=True)
        except RateLimitedError as exc:
            return SendResult(ok=False, error=str(exc), rate_limited=True)
        except Exception as exc:  # noqa: BLE001
            return SendResult(ok=False, error=str(exc))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_send_outreach.py -v`
Expected: `3 passed`.

> NOTE: CV attachment now lives in `OutreachContent.attachment_path`, set when building content (Task 5 / CLI), not in the use-case.

- [ ] **Step 5: Commit**

```bash
git add sender/app/application/send_outreach.py sender/tests/test_send_outreach.py
git commit -m "refactor: SendOutreach works with OutreachChannel and OutreachContent"
```

---

## Task 5: format_for_channel (truncation + subject)

**Files:**
- Create: `sender/app/application/format_content.py`
- Test: `sender/tests/test_format_content.py`

- [ ] **Step 1: Write the failing test**

`sender/tests/test_format_content.py`:
```python
from app.application.format_content import format_for_channel
from app.domain.channel import OutreachContent


class _Ch:
    def __init__(self, body_limit=None, needs_subject=False):
        self.name = "x"
        self.body_limit = body_limit
        self.needs_subject = needs_subject


def test_passes_body_through_when_no_limit():
    c = format_for_channel(_Ch(), body="hello world", subject="S", attachment_path="cv.pdf")
    assert c == OutreachContent(body="hello world", subject=None, attachment_path="cv.pdf")


def test_truncates_at_word_boundary_within_limit():
    ch = _Ch(body_limit=10)
    c = format_for_channel(ch, body="hello world foo", subject=None, attachment_path=None)
    assert len(c.body) <= 10
    assert c.body == "hello"  # cut at the last space before the limit


def test_hard_cut_when_no_space():
    ch = _Ch(body_limit=4)
    c = format_for_channel(ch, body="abcdefgh", subject=None, attachment_path=None)
    assert c.body == "abcd"


def test_subject_kept_only_when_needed():
    ch = _Ch(needs_subject=True)
    c = format_for_channel(ch, body="b", subject="Hi there", attachment_path=None)
    assert c.subject == "Hi there"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_format_content.py -v`
Expected: FAIL (`No module named 'app.application.format_content'`).

- [ ] **Step 3: Write the implementation**

`sender/app/application/format_content.py`:
```python
"""Adapt one generated body to a channel's limits and subject requirement."""
from app.domain.channel import OutreachContent


def _truncate(body: str, limit: int) -> str:
    if len(body) <= limit:
        return body
    window = body[:limit]
    cut = window.rfind(" ")
    if cut > 0:
        return window[:cut].rstrip()
    return window


def format_for_channel(channel, body: str, subject: str | None,
                       attachment_path: str | None) -> OutreachContent:
    out_body = body
    if channel.body_limit is not None:
        out_body = _truncate(body, channel.body_limit)
    out_subject = subject if channel.needs_subject else None
    return OutreachContent(body=out_body, subject=out_subject,
                           attachment_path=attachment_path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_format_content.py -v`
Expected: `4 passed`.

- [ ] **Step 5: Commit**

```bash
git add sender/app/application/format_content.py sender/tests/test_format_content.py
git commit -m "feat: add format_for_channel for per-channel body limits and subject"
```

---

## Task 6: Telegram adapter under the new port

**Files:**
- Create: `sender/app/infrastructure/channels/__init__.py`
- Create: `sender/app/infrastructure/channels/telegram.py`
- Test: `sender/tests/test_telegram_channel.py`

- [ ] **Step 1: Create the package init**

`sender/app/infrastructure/channels/__init__.py`: empty file.

- [ ] **Step 2: Write the failing test (target normalization is the pure, testable seam)**

`sender/tests/test_telegram_channel.py`:
```python
from app.infrastructure.channels.telegram import normalize_target


def test_normalize_strips_at():
    assert normalize_target("@nick") == "nick"


def test_normalize_extracts_from_tme_url():
    assert normalize_target("https://t.me/nick") == "nick"
    assert normalize_target("t.me/nick") == "nick"


def test_normalize_plain():
    assert normalize_target("nick") == "nick"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_telegram_channel.py -v`
Expected: FAIL (`No module named 'app.infrastructure.channels.telegram'`).

- [ ] **Step 4: Write the adapter (moves logic from telethon_client.py)**

`sender/app/infrastructure/channels/telegram.py`:
```python
"""Telegram channel: sends DMs from the user's own account via Telethon."""
import re

from telethon import TelegramClient

from app.domain.channel import OutreachContent

_CAPTION_LIMIT = 1024


def normalize_target(target: str) -> str:
    """'@nick', 'nick', 'https://t.me/nick', 't.me/nick' -> 'nick'."""
    n = target.strip()
    m = re.search(r"(?:t\.me/|telegram\.me/)(@?[\w\d_]+)", n, flags=re.IGNORECASE)
    if m:
        n = m.group(1)
    return n.lstrip("@")


class TelegramChannel:
    name = "telegram"
    body_limit = None
    needs_subject = False

    def __init__(self, session_path: str, api_id: int, api_hash: str):
        self._client = TelegramClient(session_path, api_id, api_hash)
        self._client.parse_mode = None  # raw text: don't mangle @usernames/URLs

    def start(self) -> None:
        self._client.start()

    def stop(self) -> None:
        self._client.disconnect()

    def send(self, target: str, content: OutreachContent) -> None:
        username = normalize_target(target)
        self._client.loop.run_until_complete(self._send(username, content))

    async def _send(self, username: str, content: OutreachContent) -> None:
        entity = await self._client.get_entity(username)
        attachment = content.attachment_path
        if attachment:
            if len(content.body) <= _CAPTION_LIMIT:
                await self._client.send_file(entity, attachment, caption=content.body)
            else:
                await self._client.send_message(entity, content.body)
                await self._client.send_file(entity, attachment)
        else:
            await self._client.send_message(entity, content.body)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_telegram_channel.py -v`
Expected: `3 passed`.

- [ ] **Step 6: Delete the old module and verify nothing imports it**

Run: `git rm sender/app/infrastructure/telethon_client.py`
Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests -v` (must still pass; CLI/test_send fixed in later tasks — they are not under tests/).

- [ ] **Step 7: Commit**

```bash
git add sender/app/infrastructure/channels/ sender/tests/test_telegram_channel.py
git commit -m "feat: add TelegramChannel adapter, remove old telethon_client"
```

---

## Task 7: Email adapter (SMTP)

**Files:**
- Create: `sender/app/infrastructure/channels/email_channel.py`
- Test: `sender/tests/test_email_channel.py`

- [ ] **Step 1: Write the failing test (pure builder is the seam)**

`sender/tests/test_email_channel.py`:
```python
from email.message import EmailMessage

from app.domain.channel import ChannelError, OutreachContent
from app.infrastructure.channels.email_channel import EmailChannel, build_email


def test_build_email_sets_headers_and_body():
    content = OutreachContent(body="Hello there", subject="Backend role")
    msg = build_email(content, to_addr="r@x.com", from_addr="me@x.com", from_name="Me")
    assert isinstance(msg, EmailMessage)
    assert msg["To"] == "r@x.com"
    assert msg["From"] == "Me <me@x.com>"
    assert msg["Subject"] == "Backend role"
    assert msg.get_content().strip() == "Hello there"


def test_build_email_requires_subject():
    try:
        build_email(OutreachContent(body="x", subject=None),
                    to_addr="r@x.com", from_addr="me@x.com", from_name="Me")
        assert False, "expected ChannelError"
    except ChannelError:
        pass


def test_channel_metadata():
    ch = EmailChannel(host="h", port=587, user="u", password="p", from_name="Me")
    assert ch.name == "email"
    assert ch.needs_subject is True
    assert ch.body_limit is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_email_channel.py -v`
Expected: FAIL (`No module named 'app.infrastructure.channels.email_channel'`).

- [ ] **Step 3: Write the adapter**

`sender/app/infrastructure/channels/email_channel.py`:
```python
"""Email channel: sends a personal email with CV attached via SMTP (STARTTLS)."""
import mimetypes
import smtplib
from email.message import EmailMessage
from pathlib import Path

from app.domain.channel import ChannelError, OutreachContent


def build_email(content: OutreachContent, to_addr: str, from_addr: str,
                from_name: str) -> EmailMessage:
    if not content.subject:
        raise ChannelError("email requires a subject")
    msg = EmailMessage()
    msg["From"] = f"{from_name} <{from_addr}>"
    msg["To"] = to_addr
    msg["Subject"] = content.subject
    msg.set_content(content.body)
    if content.attachment_path:
        path = Path(content.attachment_path)
        ctype, _ = mimetypes.guess_type(path.name)
        maintype, subtype = (ctype or "application/octet-stream").split("/", 1)
        msg.add_attachment(path.read_bytes(), maintype=maintype,
                           subtype=subtype, filename=path.name)
    return msg


class EmailChannel:
    name = "email"
    body_limit = None
    needs_subject = True

    def __init__(self, host: str, port: int, user: str, password: str,
                 from_name: str, smtp_factory=smtplib.SMTP):
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._from_name = from_name
        self._smtp_factory = smtp_factory  # injectable for tests

    def start(self) -> None:  # SMTP connects per-send; nothing to do here
        pass

    def stop(self) -> None:
        pass

    def send(self, target: str, content: OutreachContent) -> None:
        msg = build_email(content, to_addr=target.strip(),
                          from_addr=self._user, from_name=self._from_name)
        with self._smtp_factory(self._host, self._port) as smtp:
            smtp.starttls()
            smtp.login(self._user, self._password)
            smtp.send_message(msg)
```

- [ ] **Step 4: Add a send-path test with a fake SMTP**

Append to `sender/tests/test_email_channel.py`:
```python
def test_send_uses_smtp():
    calls = {}

    class _FakeSMTP:
        def __init__(self, host, port):
            calls["addr"] = (host, port)
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self): calls["tls"] = True
        def login(self, u, p): calls["login"] = (u, p)
        def send_message(self, msg): calls["to"] = msg["To"]

    ch = EmailChannel(host="h", port=587, user="me@x.com", password="pw",
                      from_name="Me", smtp_factory=_FakeSMTP)
    ch.send("r@x.com", OutreachContent(body="hi", subject="S"))
    assert calls["addr"] == ("h", 587)
    assert calls["tls"] is True
    assert calls["login"] == ("me@x.com", "pw")
    assert calls["to"] == "r@x.com"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_email_channel.py -v`
Expected: `4 passed`.

- [ ] **Step 6: Commit**

```bash
git add sender/app/infrastructure/channels/email_channel.py sender/tests/test_email_channel.py
git commit -m "feat: add Email channel adapter (SMTP)"
```

---

## Task 8: HeadHunter adapter (official API)

**Files:**
- Create: `sender/app/infrastructure/channels/headhunter.py`
- Test: `sender/tests/test_headhunter_channel.py`
- Modify: `sender/requirements.txt` (add `httpx`)

> **Implementer note:** verify the exact endpoint against https://api.hh.ru/openapi
> at build time. As of this plan, applying to a vacancy = `POST /negotiations`
> with form fields `vacancy_id`, `resume_id`, `message`. Vacancy id is extracted
> from the vacancy URL (`hh.ru/vacancy/<id>`). The pure functions below isolate
> this so the endpoint can be adjusted without touching tests' structure.

- [ ] **Step 1: Add httpx to requirements and install**

Add to `sender/requirements.txt`:
```
httpx==0.28.1
```
Run: `sender/.venv/Scripts/python.exe -m pip install httpx==0.28.1`
Expected: `Successfully installed httpx-0.28.1 ...`

- [ ] **Step 2: Write the failing test**

`sender/tests/test_headhunter_channel.py`:
```python
import pytest

from app.domain.channel import ChannelError, OutreachContent
from app.infrastructure.channels.headhunter import (
    HeadHunterChannel,
    extract_vacancy_id,
    post_negotiation,
)


def test_extract_vacancy_id_from_url():
    assert extract_vacancy_id("https://hh.ru/vacancy/12345?from=x") == "12345"
    assert extract_vacancy_id("12345") == "12345"


def test_extract_vacancy_id_invalid():
    with pytest.raises(ChannelError):
        extract_vacancy_id("https://hh.ru/employer/9")


def test_post_negotiation_sends_form():
    captured = {}

    class _FakeClient:
        def post(self, url, data=None):
            captured["url"] = url
            captured["data"] = data
            class _R:
                status_code = 201
                def json(self): return {}
            return _R()

    post_negotiation(_FakeClient(), resume_id="r1", vacancy_id="v1", message="hello")
    assert captured["url"].endswith("/negotiations")
    assert captured["data"] == {"vacancy_id": "v1", "resume_id": "r1", "message": "hello"}


def test_post_negotiation_raises_on_error_status():
    class _FakeClient:
        def post(self, url, data=None):
            class _R:
                status_code = 403
                text = "forbidden"
                def json(self): return {"errors": [{"value": "forbidden"}]}
            return _R()

    with pytest.raises(ChannelError):
        post_negotiation(_FakeClient(), resume_id="r1", vacancy_id="v1", message="hi")


def test_channel_metadata():
    ch = HeadHunterChannel(access_token="t", resume_id="r1")
    assert ch.name == "hh"
    assert ch.needs_subject is False
```

- [ ] **Step 3: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_headhunter_channel.py -v`
Expected: FAIL (`No module named 'app.infrastructure.channels.headhunter'`).

- [ ] **Step 4: Write the adapter**

`sender/app/infrastructure/channels/headhunter.py`:
```python
"""HeadHunter channel: applies to a vacancy (negotiation) via the official API."""
import re

import httpx

from app.domain.channel import ChannelError, OutreachContent, RateLimitedError

_API_BASE = "https://api.hh.ru"
_VACANCY_RE = re.compile(r"hh\.ru/vacancy/(\d+)")


def extract_vacancy_id(target: str) -> str:
    t = target.strip()
    if t.isdigit():
        return t
    m = _VACANCY_RE.search(t)
    if not m:
        raise ChannelError(f"cannot extract hh.ru vacancy id from: {target}")
    return m.group(1)


def post_negotiation(client, resume_id: str, vacancy_id: str, message: str) -> None:
    resp = client.post(
        f"{_API_BASE}/negotiations",
        data={"vacancy_id": vacancy_id, "resume_id": resume_id, "message": message},
    )
    if resp.status_code in (429, 403):
        raise RateLimitedError(f"hh.ru throttled/blocked: {resp.status_code}")
    if resp.status_code >= 400:
        raise ChannelError(f"hh.ru negotiation failed: {resp.status_code} {resp.text}")


class HeadHunterChannel:
    name = "hh"
    body_limit = None
    needs_subject = False

    def __init__(self, access_token: str, resume_id: str):
        self._token = access_token
        self._resume_id = resume_id
        self._client: httpx.Client | None = None

    def start(self) -> None:
        self._client = httpx.Client(
            headers={"Authorization": f"Bearer {self._token}",
                     "User-Agent": "telegram-jobs-sender/1.0"},
            timeout=30.0,
        )

    def stop(self) -> None:
        if self._client:
            self._client.close()

    def send(self, target: str, content: OutreachContent) -> None:
        if self._client is None:
            raise ChannelError("HeadHunterChannel.start() not called")
        vacancy_id = extract_vacancy_id(target)
        post_negotiation(self._client, self._resume_id, vacancy_id, content.body)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_headhunter_channel.py -v`
Expected: `5 passed`.

- [ ] **Step 6: Commit**

```bash
git add sender/app/infrastructure/channels/headhunter.py sender/tests/test_headhunter_channel.py sender/requirements.txt
git commit -m "feat: add HeadHunter channel adapter (official API)"
```

---

## Task 9: LinkedIn adapter (Playwright)

**Files:**
- Create: `sender/app/infrastructure/channels/linkedin.py`
- Test: `sender/tests/test_linkedin_channel.py`
- Modify: `sender/requirements.txt` (add `playwright`)

> **Implementer note:** LinkedIn selectors change often and automation violates
> LinkedIn ToS (accepted by the user). Keep the DOM interaction in the pure
> `fill_and_send(page, content)` function so selectors can be updated in one place
> and tested against a fake page. The class only wires Playwright session handling.

- [ ] **Step 1: Add playwright to requirements and install browsers**

Add to `sender/requirements.txt`:
```
playwright==1.49.1
```
Run: `sender/.venv/Scripts/python.exe -m pip install playwright==1.49.1`
Run: `sender/.venv/Scripts/python.exe -m playwright install chromium`
Expected: chromium downloaded.

- [ ] **Step 2: Write the failing test (fake page records actions)**

`sender/tests/test_linkedin_channel.py`:
```python
import pytest

from app.domain.channel import ChannelError, OutreachContent
from app.infrastructure.channels.linkedin import fill_and_send


class _FakePage:
    def __init__(self, message_button=True):
        self.actions = []
        self._has_message = message_button

    def goto(self, url, **kw):
        self.actions.append(("goto", url))

    def get_by_role(self, role, name=None):
        self.actions.append(("get_by_role", role, name))
        page = self
        class _Locator:
            def count(self_inner):
                if name == "Message":
                    return 1 if page._has_message else 0
                return 1
            def first(self_inner): return self_inner
            def click(self_inner): page.actions.append(("click", name))
        return _Locator()

    def get_by_label(self, label, **kw):
        page = self
        class _Box:
            def fill(self_inner, text): page.actions.append(("fill", label, text))
        return _Box()

    def keyboard_press(self, key):
        self.actions.append(("press", key))


def test_fill_and_send_messages_connection():
    page = _FakePage(message_button=True)
    fill_and_send(page, "https://linkedin.com/in/someone",
                  OutreachContent(body="Hi there"))
    assert ("goto", "https://linkedin.com/in/someone") in page.actions
    assert ("click", "Message") in page.actions
    assert any(a[0] == "fill" and a[2] == "Hi there" for a in page.actions)


def test_fill_and_send_raises_without_message_button():
    page = _FakePage(message_button=False)
    with pytest.raises(ChannelError):
        fill_and_send(page, "https://linkedin.com/in/x", OutreachContent(body="Hi"))
```

- [ ] **Step 3: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_linkedin_channel.py -v`
Expected: FAIL (`No module named 'app.infrastructure.channels.linkedin'`).

- [ ] **Step 4: Write the adapter**

`sender/app/infrastructure/channels/linkedin.py`:
```python
"""LinkedIn channel: sends a message to a profile via a logged-in browser session.

Automating LinkedIn violates its ToS and risks an account ban (accepted by the
user). DOM interaction is isolated in fill_and_send() because selectors drift.
"""
from app.domain.channel import ChannelError, OutreachContent


def fill_and_send(page, profile_url: str, content: OutreachContent) -> None:
    """Open a profile and send a message. `page` is a Playwright Page (or a fake)."""
    page.goto(profile_url, wait_until="domcontentloaded")
    msg_btn = page.get_by_role("button", name="Message")
    if msg_btn.count() == 0:
        # Not a 1st-degree connection: a message box is unavailable here.
        raise ChannelError(f"no Message button on {profile_url} (not connected?)")
    msg_btn.first().click()
    page.get_by_label("Write a message…").fill(content.body)
    page.keyboard_press("Enter")


class LinkedInChannel:
    name = "linkedin"
    body_limit = 300          # safe for connection notes; messages allow more
    needs_subject = False

    def __init__(self, storage_state_path: str, headless: bool = False):
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
            self._page.goto("https://www.linkedin.com/login")
            input("Залогинься в LinkedIn в открытом окне, потом нажми Enter здесь...")
            context.storage_state(path=self._storage_state_path)

    def stop(self) -> None:
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def send(self, target: str, content: OutreachContent) -> None:
        if self._page is None:
            raise ChannelError("LinkedInChannel.start() not called")
        fill_and_send(self._page, target.strip(), content)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_linkedin_channel.py -v`
Expected: `2 passed`.

- [ ] **Step 6: Commit**

```bash
git add sender/app/infrastructure/channels/linkedin.py sender/tests/test_linkedin_channel.py sender/requirements.txt
git commit -m "feat: add LinkedIn channel adapter (Playwright)"
```

---

## Task 10: Wellfound adapter (Playwright)

**Files:**
- Create: `sender/app/infrastructure/channels/wellfound.py`
- Test: `sender/tests/test_wellfound_channel.py`

> **Implementer note:** like LinkedIn, selectors must be verified at build time.
> Wellfound applications open an "Apply" dialog with a message textarea. Keep DOM
> logic in `apply_via_page`.

- [ ] **Step 1: Write the failing test**

`sender/tests/test_wellfound_channel.py`:
```python
import pytest

from app.domain.channel import ChannelError, OutreachContent
from app.infrastructure.channels.wellfound import apply_via_page


class _FakePage:
    def __init__(self, has_apply=True):
        self.actions = []
        self._has_apply = has_apply

    def goto(self, url, **kw):
        self.actions.append(("goto", url))

    def get_by_role(self, role, name=None):
        page = self
        class _Locator:
            def count(self_inner):
                return 1 if (name != "Apply" or page._has_apply) else 0
            def first(self_inner): return self_inner
            def click(self_inner): page.actions.append(("click", name))
        return _Locator()

    def get_by_placeholder(self, text):
        page = self
        class _Box:
            def fill(self_inner, value): page.actions.append(("fill", value))
        return _Box()


def test_apply_fills_message_and_submits():
    page = _FakePage(has_apply=True)
    apply_via_page(page, "https://wellfound.com/jobs/123", OutreachContent(body="Hi team"))
    assert ("goto", "https://wellfound.com/jobs/123") in page.actions
    assert ("click", "Apply") in page.actions
    assert ("fill", "Hi team") in page.actions
    assert ("click", "Submit application") in page.actions


def test_apply_raises_without_apply_button():
    page = _FakePage(has_apply=False)
    with pytest.raises(ChannelError):
        apply_via_page(page, "https://wellfound.com/jobs/1", OutreachContent(body="Hi"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_wellfound_channel.py -v`
Expected: FAIL (`No module named 'app.infrastructure.channels.wellfound'`).

- [ ] **Step 3: Write the adapter**

`sender/app/infrastructure/channels/wellfound.py`:
```python
"""Wellfound channel: applies to a job via a logged-in browser session.

Automating Wellfound violates its ToS and risks an account ban (accepted by the
user). DOM interaction is isolated in apply_via_page() because selectors drift.
"""
from app.domain.channel import ChannelError, OutreachContent


def apply_via_page(page, job_url: str, content: OutreachContent) -> None:
    page.goto(job_url, wait_until="domcontentloaded")
    apply_btn = page.get_by_role("button", name="Apply")
    if apply_btn.count() == 0:
        raise ChannelError(f"no Apply button on {job_url}")
    apply_btn.first().click()
    page.get_by_placeholder("Write a note…").fill(content.body)
    page.get_by_role("button", name="Submit application").first().click()


class WellfoundChannel:
    name = "wellfound"
    body_limit = None
    needs_subject = False

    def __init__(self, storage_state_path: str, headless: bool = False):
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

    def send(self, target: str, content: OutreachContent) -> None:
        if self._page is None:
            raise ChannelError("WellfoundChannel.start() not called")
        apply_via_page(self._page, target.strip(), content)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_wellfound_channel.py -v`
Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add sender/app/infrastructure/channels/wellfound.py sender/tests/test_wellfound_channel.py
git commit -m "feat: add Wellfound channel adapter (Playwright)"
```

---

## Task 11: Per-platform config

**Files:**
- Modify: `sender/app/config.py`
- Test: `sender/tests/test_config_platforms.py`

- [ ] **Step 1: Write the failing test (pure helper, env-driven)**

`sender/tests/test_config_platforms.py`:
```python
from app.config import platform_enabled


def test_telegram_enabled_when_api_id_present():
    env = {"TELEGRAM_API_ID": "1", "TELEGRAM_API_HASH": "h"}
    assert platform_enabled("telegram", env) is True


def test_email_enabled_requires_host_and_user():
    assert platform_enabled("email", {"SMTP_HOST": "h", "SMTP_USER": "u"}) is True
    assert platform_enabled("email", {"SMTP_HOST": "h"}) is False


def test_unknown_platform_disabled():
    assert platform_enabled("nope", {}) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_config_platforms.py -v`
Expected: FAIL (`cannot import name 'platform_enabled'`).

- [ ] **Step 3: Add config blocks and the helper to `sender/app/config.py`**

Add near the bottom of `sender/app/config.py` (after existing settings, before any
`run`-only code):
```python
# --- Per-platform settings (all optional; a platform is enabled when configured) ---

# LinkedIn / Wellfound browser sessions
LINKEDIN_STATE_PATH = os.environ.get(
    "LINKEDIN_STATE_PATH", str(_ROOT / "sender" / "linkedin_state.json"))
WELLFOUND_STATE_PATH = os.environ.get(
    "WELLFOUND_STATE_PATH", str(_ROOT / "sender" / "wellfound_state.json"))
BROWSER_HEADLESS = os.environ.get("BROWSER_HEADLESS", "false").lower() == "true"

# HeadHunter
HH_ACCESS_TOKEN = os.environ.get("HH_ACCESS_TOKEN", "")
HH_RESUME_ID = os.environ.get("HH_RESUME_ID", "")

# Email (SMTP)
SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME", "")


def platform_enabled(platform: str, env=None) -> bool:
    """True if the env has the minimum vars to build this platform's channel."""
    env = os.environ if env is None else env
    if platform == "telegram":
        return bool(env.get("TELEGRAM_API_ID") and env.get("TELEGRAM_API_HASH"))
    if platform == "linkedin":
        return True  # browser login is interactive; always available
    if platform == "wellfound":
        return True
    if platform == "hh":
        return bool(env.get("HH_ACCESS_TOKEN") and env.get("HH_RESUME_ID"))
    if platform == "email":
        return bool(env.get("SMTP_HOST") and env.get("SMTP_USER"))
    return False
```

> NOTE: `TELEGRAM_API_ID`/`HASH` reads at the top of config.py currently use
> `os.environ[...]` (hard requirement). Leave them — Telegram stays required as
> today; the helper just reports enabled state for the registry.

- [ ] **Step 4: Run tests to verify they pass**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_config_platforms.py -v`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add sender/app/config.py sender/tests/test_config_platforms.py
git commit -m "feat: add per-platform config and platform_enabled helper"
```

---

## Task 12: Channel registry

**Files:**
- Create: `sender/app/infrastructure/channels/registry.py`
- Test: `sender/tests/test_registry.py`

- [ ] **Step 1: Write the failing test**

`sender/tests/test_registry.py`:
```python
import pytest

from app.infrastructure.channels.registry import build_channel
from app.infrastructure.channels.email_channel import EmailChannel
from app.infrastructure.channels.headhunter import HeadHunterChannel


class _Cfg:
    SMTP_HOST = "h"; SMTP_PORT = 587; SMTP_USER = "u"; SMTP_PASSWORD = "p"
    EMAIL_FROM_NAME = "Me"
    HH_ACCESS_TOKEN = "t"; HH_RESUME_ID = "r"
    TELEGRAM_API_ID = 1; TELEGRAM_API_HASH = "h"; SESSION_PATH = "s"
    LINKEDIN_STATE_PATH = "l.json"; WELLFOUND_STATE_PATH = "w.json"
    BROWSER_HEADLESS = True


def test_build_email_channel():
    assert isinstance(build_channel("email", _Cfg()), EmailChannel)


def test_build_hh_channel():
    assert isinstance(build_channel("hh", _Cfg()), HeadHunterChannel)


def test_unknown_platform_raises():
    with pytest.raises(ValueError):
        build_channel("myspace", _Cfg())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_registry.py -v`
Expected: FAIL (`No module named '...registry'`).

- [ ] **Step 3: Write the registry**

`sender/app/infrastructure/channels/registry.py`:
```python
"""Map a platform string to a freshly-built (not yet started) OutreachChannel."""
from app.infrastructure.channels.email_channel import EmailChannel
from app.infrastructure.channels.headhunter import HeadHunterChannel
from app.infrastructure.channels.linkedin import LinkedInChannel
from app.infrastructure.channels.telegram import TelegramChannel
from app.infrastructure.channels.wellfound import WellfoundChannel


def build_channel(platform: str, config):
    if platform == "telegram":
        return TelegramChannel(config.SESSION_PATH, config.TELEGRAM_API_ID,
                               config.TELEGRAM_API_HASH)
    if platform == "email":
        return EmailChannel(config.SMTP_HOST, config.SMTP_PORT, config.SMTP_USER,
                            config.SMTP_PASSWORD, config.EMAIL_FROM_NAME)
    if platform == "hh":
        return HeadHunterChannel(config.HH_ACCESS_TOKEN, config.HH_RESUME_ID)
    if platform == "linkedin":
        return LinkedInChannel(config.LINKEDIN_STATE_PATH, config.BROWSER_HEADLESS)
    if platform == "wellfound":
        return WellfoundChannel(config.WELLFOUND_STATE_PATH, config.BROWSER_HEADLESS)
    raise ValueError(f"unknown platform: {platform}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_registry.py -v`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add sender/app/infrastructure/channels/registry.py sender/tests/test_registry.py
git commit -m "feat: add channel registry mapping platform -> adapter"
```

---

## Task 13: Contract test — every adapter satisfies the port

**Files:**
- Test: `sender/tests/test_channel_contract.py`

- [ ] **Step 1: Write the contract test**

`sender/tests/test_channel_contract.py`:
```python
import pytest

from app.domain.channel import OutreachChannel
from app.infrastructure.channels.email_channel import EmailChannel
from app.infrastructure.channels.headhunter import HeadHunterChannel
from app.infrastructure.channels.linkedin import LinkedInChannel
from app.infrastructure.channels.telegram import TelegramChannel
from app.infrastructure.channels.wellfound import WellfoundChannel

_CHANNELS = [
    EmailChannel("h", 587, "u", "p", "Me"),
    HeadHunterChannel("t", "r"),
    LinkedInChannel("l.json", True),
    WellfoundChannel("w.json", True),
    # TelegramChannel constructs a TelegramClient; skip instantiation, check class attrs.
]


@pytest.mark.parametrize("ch", _CHANNELS)
def test_satisfies_protocol(ch):
    assert isinstance(ch, OutreachChannel)
    assert ch.name in {"telegram", "linkedin", "hh", "email", "wellfound"}
    assert ch.body_limit is None or isinstance(ch.body_limit, int)
    assert isinstance(ch.needs_subject, bool)


def test_telegram_class_attrs():
    assert TelegramChannel.name == "telegram"
    assert TelegramChannel.needs_subject is False
```

- [ ] **Step 2: Run the contract test**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_channel_contract.py -v`
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add sender/tests/test_channel_contract.py
git commit -m "test: contract test that every adapter satisfies OutreachChannel"
```

---

## Task 14: SheetsRepo reads platform/target + writes notes

**Files:**
- Modify: `sender/app/infrastructure/sheets_repo.py`
- Test: `sender/tests/test_sheets_mapping.py`

> The real gspread worksheet needs network/credentials; test the pure record→Lead
> mapping by extracting it into a module-level function.

- [ ] **Step 1: Write the failing test**

`sender/tests/test_sheets_mapping.py`:
```python
from app.infrastructure.sheets_repo import record_to_lead


def test_maps_platform_and_target():
    rec = {
        "id": "5", "Платформа": "linkedin", "Цель": "https://linkedin.com/in/x",
        "Вакансия": "Backend", "Исходный текст": "raw", "Статус": "new",
    }
    lead = record_to_lead(rec, offset=0)
    assert lead.row == 2
    assert lead.platform == "linkedin"
    assert lead.target == "https://linkedin.com/in/x"


def test_defaults_platform_when_empty():
    rec = {"id": "1", "Платформа": "", "Цель": "@nick", "Статус": "new"}
    lead = record_to_lead(rec, offset=3)
    assert lead.row == 5
    assert lead.platform == "telegram"
    assert lead.target == "@nick"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_sheets_mapping.py -v`
Expected: FAIL (`cannot import name 'record_to_lead'`).

- [ ] **Step 3: Replace `sender/app/infrastructure/sheets_repo.py`**

```python
"""Google Sheets repository for the sender: read `new` leads, update status."""
import datetime as _dt

import gspread
from google.oauth2.service_account import Credentials

from app.domain.lead import (
    COL_DATE_SENT,
    COL_MESSAGE,
    COL_NOTE,
    COL_STATUS,
    COLUMNS,
    DEFAULT_PLATFORM,
    STATUS_NEW,
    Lead,
)

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _load_credentials(service_account_path: str) -> Credentials:
    return Credentials.from_service_account_file(service_account_path, scopes=_SCOPES)


def record_to_lead(rec: dict, offset: int) -> Lead:
    """Map one sheet record to a Lead. `offset` is the 0-based data-row index."""
    platform = str(rec.get("Платформа", "")).strip().lower() or DEFAULT_PLATFORM
    return Lead(
        row=offset + 2,  # +1 header, +1 to 1-based
        lead_id=str(rec.get("id", "")),
        platform=platform,
        target=str(rec.get("Цель", "")).strip(),
        vacancy_context=str(rec.get("Вакансия", "")).strip(),
        raw_text=str(rec.get("Исходный текст", "")).strip(),
        status=STATUS_NEW,
    )


class SheetsRepo:
    def __init__(self, service_account_path: str, sheet_id: str, tab: str):
        client = gspread.authorize(_load_credentials(service_account_path))
        self._ws = client.open_by_key(sheet_id).worksheet(tab)

    def fetch_new_leads(self) -> list[Lead]:
        records = self._ws.get_all_records(expected_headers=COLUMNS)
        return [
            record_to_lead(rec, offset)
            for offset, rec in enumerate(records)
            if str(rec.get("Статус", "")).strip() == STATUS_NEW
        ]

    def mark_sent(self, lead: Lead, message: str, status: str) -> None:
        now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        self._ws.update_cell(lead.row, COL_MESSAGE, message)
        self._ws.update_cell(lead.row, COL_STATUS, status)
        self._ws.update_cell(lead.row, COL_DATE_SENT, now)

    def mark_status(self, lead: Lead, status: str, note: str = "") -> None:
        self._ws.update_cell(lead.row, COL_STATUS, status)
        if note:
            self._ws.update_cell(lead.row, COL_NOTE, note)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_sheets_mapping.py -v`
Expected: `2 passed`.

- [ ] **Step 5: Commit**

```bash
git add sender/app/infrastructure/sheets_repo.py sender/tests/test_sheets_mapping.py
git commit -m "feat: SheetsRepo reads platform/target and writes notes"
```

---

## Task 15: Subject generation for email

**Files:**
- Modify: `sender/app/application/generate_message.py`
- Test: `sender/tests/test_generate_subject.py`

- [ ] **Step 1: Write the failing test**

`sender/tests/test_generate_subject.py`:
```python
from app.application.generate_message import subject_for


def test_subject_uses_vacancy_first_line():
    assert subject_for("Backend Engineer at Acme\nRemote, Python") == \
        "Backend Engineer at Acme"


def test_subject_falls_back_when_empty():
    assert subject_for("") == "Заявка на вакансию"


def test_subject_is_trimmed_to_one_line_and_capped():
    long = "x" * 200
    s = subject_for(long)
    assert "\n" not in s
    assert len(s) <= 120
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_generate_subject.py -v`
Expected: FAIL (`cannot import name 'subject_for'`).

- [ ] **Step 3: Add `subject_for` to `sender/app/application/generate_message.py`**

Append to the file:
```python
def subject_for(vacancy_context: str) -> str:
    """A short email subject derived from the vacancy text (first non-empty line)."""
    for line in vacancy_context.splitlines():
        line = line.strip()
        if line:
            return line[:120]
    return "Заявка на вакансию"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_generate_subject.py -v`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add sender/app/application/generate_message.py sender/tests/test_generate_subject.py
git commit -m "feat: derive email subject from vacancy context"
```

---

## Task 16: CLI — multi-platform send loop

**Files:**
- Modify: `sender/app/interface/cli.py`
- Modify: `sender/test_send.py` (adapt to new API)

> This task is integration wiring; it has no new unit test (the units are covered).
> Verify by import + a dry run.

- [ ] **Step 1: Replace `sender/app/interface/cli.py`**

```python
"""Interactive CLI: read `new` leads, generate, approve, send across platforms.

One run walks every new lead, picks the channel for its platform, and sends.
Default mode asks send/edit/skip per lead. AUTO_SEND=true sends automatically.
Per-platform daily limits and anti-ban delays apply.
"""
import random
import time

from app import config
from app.application.format_content import format_for_channel
from app.application.generate_message import GenerateMessage, subject_for
from app.application.send_outreach import SendOutreach
from app.domain.lead import STATUS_FAILED, STATUS_SENT, STATUS_SKIPPED
from app.infrastructure.channels.registry import build_channel
from app.infrastructure.cv_loader import load_cv_text, load_text_file
from app.infrastructure.openai_client import OpenAIMessageGenerator
from app.infrastructure.sheets_repo import SheetsRepo

_KNOWN = {"telegram", "linkedin", "hh", "email", "wellfound"}


def _prompt(msg: str) -> str:
    try:
        return input(msg).strip()
    except EOFError:
        return ""


def _show(message: str) -> None:
    print("\n--- СООБЩЕНИЕ ---\n" + message + "\n-----------------")


def run() -> None:
    print("== telegram-jobs sender (multi-platform) ==")
    cv_text = load_cv_text(config.CV_PATH)
    profile_text = load_text_file(config.PROFILE_PATH)

    repo = SheetsRepo(config.GOOGLE_SERVICE_ACCOUNT_FILE, config.SHEET_ID, config.SHEET_TAB)
    generator = GenerateMessage(
        OpenAIMessageGenerator(config.OPENAI_API_KEY, config.OPENAI_MODEL),
        cv_text, profile_text, config.SIGNATURE_TEXT,
    )

    leads = repo.fetch_new_leads()
    if not leads:
        print("Нет новых лидов (статус 'new'). Выход.")
        return

    mode = "АВТО (без подтверждения)" if config.AUTO_SEND else "ручной"
    print(f"Новых лидов: {len(leads)}. Лимит/платформа: {config.DAILY_SEND_LIMIT}. Режим: {mode}.")

    channels: dict[str, object] = {}     # platform -> started channel
    sent_per_platform: dict[str, int] = {}
    blocked: set[str] = set()            # platforms stopped by rate-limit

    def _channel_for(platform: str):
        if platform in channels:
            return channels[platform]
        ch = build_channel(platform, config)
        print(f"Подключаюсь к каналу '{platform}'...")
        ch.start()
        channels[platform] = ch
        return ch

    try:
        for lead in leads:
            platform = lead.platform
            if platform not in _KNOWN:
                repo.mark_status(lead, STATUS_SKIPPED, note=f"unknown platform: {platform}")
                print(f"⏭  Лид #{lead.lead_id}: неизвестная платформа '{platform}', пропуск.")
                continue
            if platform in blocked:
                repo.mark_status(lead, STATUS_SKIPPED, note="platform rate-limited this run")
                continue
            if sent_per_platform.get(platform, 0) >= config.DAILY_SEND_LIMIT:
                repo.mark_status(lead, STATUS_SKIPPED, note="daily limit reached")
                continue

            print("\n" + "=" * 60)
            print(f"Лид #{lead.lead_id}  [{platform}]  →  {lead.target}")
            print(f"Вакансия: {lead.vacancy_context or lead.raw_text}")
            print("-" * 60)

            try:
                channel = _channel_for(platform)
            except Exception as exc:  # noqa: BLE001
                repo.mark_status(lead, STATUS_FAILED, note=f"channel start failed: {exc}")
                print(f"❌ Не удалось поднять канал '{platform}': {exc}")
                continue

            sender = SendOutreach(channel)
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
                    return

            result = sender.execute(lead, content)
            if result.ok:
                repo.mark_sent(lead, content.body, STATUS_SENT)
                sent_per_platform[platform] = sent_per_platform.get(platform, 0) + 1
                print(f"✅ Отправлено [{platform}] "
                      f"({sent_per_platform[platform]}/{config.DAILY_SEND_LIMIT}).")
                delay = random.randint(config.MIN_DELAY_SECONDS, config.MAX_DELAY_SECONDS)
                print(f"⏳ Пауза {delay} c (анти-бан)...")
                time.sleep(delay)
            elif result.rate_limited:
                repo.mark_status(lead, STATUS_SKIPPED, note="rate-limited")
                blocked.add(platform)
                print(f"🛑 Платформа '{platform}' ограничила нас — останавливаю её на этот запуск.")
            else:
                repo.mark_status(lead, STATUS_FAILED, note=result.error)
                print(f"❌ Ошибка отправки: {result.error}")
    finally:
        for ch in channels.values():
            try:
                ch.stop()
            except Exception:  # noqa: BLE001
                pass
        total = sum(sent_per_platform.values())
        print(f"\nГотово. Отправлено за сессию: {total}. По платформам: {sent_per_platform}")


if __name__ == "__main__":
    run()
```

- [ ] **Step 2: Update `sender/test_send.py` to the new API**

Replace its body references:
- Import `from app.infrastructure.channels.telegram import TelegramChannel` instead of `telethon_client`.
- Replace `lead.nickname` prints with `lead.target`.
- Build content: `from app.domain.channel import OutreachContent` and send via
  `TelegramChannel(...).send(args.to, OutreachContent(body=message, attachment_path=attachment))`.

Concretely, change the imports block and the send block:
```python
from app.infrastructure.channels.telegram import TelegramChannel  # noqa: E402
from app.domain.channel import OutreachContent  # noqa: E402
```
```python
    print(f"Лид #{lead.lead_id}  ->  {lead.target}")
```
```python
    messenger = TelegramChannel(
        config.SESSION_PATH, config.TELEGRAM_API_ID, config.TELEGRAM_API_HASH
    )
    messenger.start()
    try:
        attachment = config.CV_PATH if config.ATTACH_CV else None
        messenger.send(args.to, OutreachContent(body=message, attachment_path=attachment))
        print("✅ Тест отправлен. Проверь Telegram.")
    finally:
        messenger.stop()
```

- [ ] **Step 3: Verify the whole suite still passes**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests -v`
Expected: all tests pass.

- [ ] **Step 4: Verify CLI imports cleanly (no run)**

Run: `sender/.venv/Scripts/python.exe -c "import sys; sys.path.insert(0,'sender'); import app.interface.cli; print('ok')"`
Expected: prints `ok` (set required env vars first, or expect a clear config error — that is acceptable here).

- [ ] **Step 5: Commit**

```bash
git add sender/app/interface/cli.py sender/test_send.py
git commit -m "feat: multi-platform send loop with per-platform limits and rate-limit handling"
```

---

## Task 17: Docs, env example, requirements, Makefile, intake sync

**Files:**
- Modify: `.env.example`
- Modify: `Makefile`
- Modify: `README.md`
- Modify: `google-apps-script/Formatting.gs` (column sync)
- Modify: `intake-bot/app/domain/lead.py` and/or wherever COLUMNS lives in intake

- [ ] **Step 1: Update `.env.example`**

Append a documented per-platform block:
```
# --- LinkedIn / Wellfound (browser automation; ToS risk accepted) ---
LINKEDIN_STATE_PATH=sender/linkedin_state.json
WELLFOUND_STATE_PATH=sender/wellfound_state.json
BROWSER_HEADLESS=false

# --- HeadHunter (official API) ---
HH_ACCESS_TOKEN=
HH_RESUME_ID=

# --- Email (SMTP, e.g. Gmail app password) ---
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
EMAIL_FROM_NAME=
```

- [ ] **Step 2: Sync the intake column order**

Open the intake's column definition (search): 
Run: `sender/.venv/Scripts/python.exe -c "print('locate COLUMNS in intake-bot and Formatting.gs')"`
Then edit `intake-bot` lead columns and `google-apps-script/Formatting.gs` so the
header row matches exactly:
`id, Дата добавления, Исходный текст, Платформа, Цель, Вакансия, Сообщение, Статус, Дата отправки, Заметка`

> For sub-project B, the intake bot may write `Платформа=telegram` and
> `Цель=<the old Ник/ссылка value>` as a default. Full auto-detection is sub-project A.

- [ ] **Step 3: Add a Makefile target for tests**

Add to `Makefile`:
```
test-unit:
	$(PYTHON) -m pytest sender/tests -v
```
And add `test-unit` to the `.PHONY` line.

- [ ] **Step 4: Update README**

Add a short "Платформы" section listing the five channels, how to enable each
(env vars), the one-time browser login for LinkedIn/Wellfound, and a note that
LinkedIn/Wellfound automation violates their ToS and risks an account ban.

- [ ] **Step 5: Run the full suite once more**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests -v`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add .env.example Makefile README.md google-apps-script/Formatting.gs intake-bot/
git commit -m "docs: document multi-platform setup and sync sheet columns"
```

---

## Self-Review notes (for the implementer)

- **Spec coverage:** port (T2), content/limits (T2,T5), 5 adapters (T6–T10), registry (T12), lazy start + per-platform limits + rate-limit stop (T16), data model (T3,T14), subject for email (T15), config (T11), tests incl. contract (all + T13), docs/env (T17). The "Ник/ссылка → Цель" rename is handled in T3/T14; back-compat default `telegram` covers old rows.
- **Type consistency:** `OutreachContent(body, subject, attachment_path)` and the channel attrs `name/body_limit/needs_subject` are used identically across all tasks. `SendOutreach(channel)` single-arg is consistent T4→T16. `mark_status(lead, status, note="")` defined T14, used T16.
- **Known real-world risk:** LinkedIn/Wellfound selectors and the hh.ru endpoint must be verified live during T8–T10; tests mock the seam so structure holds even if selectors change.
