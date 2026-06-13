# Intake Platform/Target Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the intake bot auto-detect the platform (telegram/email/linkedin/hh/wellfound) and the correct target from pasted vacancy text, filling the "Платформа"/"Цель" columns automatically.

**Architecture:** Hybrid — a pure deterministic `detect_contact()` (regex, fixed priority) decides platform+target; OpenAI is reduced to a vacancy summarizer. `ExtractLeadFromText` orchestrates detect → summarize → save. Pure functions are isolated so unit tests need no network.

**Tech Stack:** Python 3.11+, FastAPI (Vercel serverless, unchanged), OpenAI, gspread, pytest (dev-only). The intake bot has no venv of its own; tests run with the sender's interpreter `sender/.venv/Scripts/python.exe` (pytest already installed there).

---

## File Structure

**New files:**
- `intake-bot/requirements-dev.txt` — pytest (documentation of the dev dep).
- `intake-bot/tests/__init__.py`, `intake-bot/tests/conftest.py` — make `app` importable.
- `intake-bot/app/domain/contact.py` — `Contact` + `detect_contact` (pure regex).
- Test files under `intake-bot/tests/`.

**Modified files:**
- `intake-bot/app/domain/lead.py` — `ExtractedLead.nickname` → `target`; `platform` no default.
- `intake-bot/app/infrastructure/openai_client.py` — `OpenAIExtractor` → `OpenAISummarizer` (`summarize(text) -> str`, error → `""`).
- `intake-bot/app/application/extract_lead.py` — orchestrate detector + summarizer + repo.
- `intake-bot/app/infrastructure/sheets_repo.py` — pure `lead_to_row` + write `lead.target`.
- `intake-bot/api/webhook.py` — wire new use-case, success/no_contact messages.
- `README.md` — note intake auto-detection.

**Platform values (must match the sender):** `telegram | email | linkedin | hh | wellfound`.

**Test interpreter (used in every Run step):** `sender/.venv/Scripts/python.exe`

---

## Task 1: Test infrastructure for intake-bot

**Files:**
- Create: `intake-bot/requirements-dev.txt`
- Create: `intake-bot/tests/__init__.py`
- Create: `intake-bot/tests/conftest.py`
- Create: `intake-bot/tests/test_smoke.py`

- [ ] **Step 1: Create dev requirements**

`intake-bot/requirements-dev.txt`:
```
pytest==8.3.4
```

- [ ] **Step 2: Confirm pytest is available via the sender venv**

Run: `sender/.venv/Scripts/python.exe -m pytest --version`
Expected: prints `pytest 8.3.4`. (If missing, run `sender/.venv/Scripts/python.exe -m pip install pytest==8.3.4`.)

- [ ] **Step 3: Make `app` importable from intake tests**

`intake-bot/tests/__init__.py`: empty file.

`intake-bot/tests/conftest.py`:
```python
"""Put the intake-bot package root on sys.path so `import app...` works in tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
```

- [ ] **Step 4: Write a smoke test**

`intake-bot/tests/test_smoke.py`:
```python
def test_pytest_runs():
    assert True
```

- [ ] **Step 5: Run the smoke test**

Run: `sender/.venv/Scripts/python.exe -m pytest intake-bot/tests/test_smoke.py -v`
Expected: `1 passed`.

- [ ] **Step 6: Commit**

```bash
git add intake-bot/requirements-dev.txt intake-bot/tests/
git commit -m "test: add pytest infrastructure for intake-bot"
```

---

## Task 2: `Contact` + `detect_contact` (pure regex core)

**Files:**
- Create: `intake-bot/app/domain/contact.py`
- Test: `intake-bot/tests/test_detect_contact.py`

- [ ] **Step 1: Write the failing test**

`intake-bot/tests/test_detect_contact.py`:
```python
from app.domain.contact import Contact, detect_contact


def test_telegram_handle():
    c = detect_contact("Ищем backend. Пиши @ivan_hr по вакансии")
    assert c == Contact("telegram", "@ivan_hr")


def test_telegram_tme_link():
    c = detect_contact("Контакт: https://t.me/ivanhr спасибо")
    assert c.platform == "telegram"
    assert "t.me/ivanhr" in c.target


def test_email():
    c = detect_contact("Резюме на recruiter@company.com")
    assert c == Contact("email", "recruiter@company.com")


def test_plain_email_is_not_telegram():
    # the @ is part of an email, not a Telegram handle
    c = detect_contact("john@gmail.com")
    assert c.platform == "email"
    assert c.target == "john@gmail.com"


def test_linkedin():
    c = detect_contact("Профиль: linkedin.com/in/ivan-ivanov апплай тут")
    assert c.platform == "linkedin"
    assert "linkedin.com/in/ivan-ivanov" in c.target


def test_hh():
    c = detect_contact("Откликнуться: https://hh.ru/vacancy/12345?from=x")
    assert c.platform == "hh"
    assert "hh.ru/vacancy/12345" in c.target


def test_wellfound():
    c = detect_contact("Apply at https://wellfound.com/jobs/987-backend-engineer")
    assert c.platform == "wellfound"
    assert "wellfound.com/jobs/987-backend-engineer" in c.target


def test_priority_telegram_over_email():
    c = detect_contact("Пиши @ivan_hr или на boss@company.com")
    assert c.platform == "telegram"


def test_priority_email_over_linkedin():
    c = detect_contact("mail me@x.com or linkedin.com/in/me")
    assert c.platform == "email"


def test_none_when_no_contact():
    assert detect_contact("Просто описание вакансии без контактов") is None


def test_strips_trailing_punctuation_from_url():
    c = detect_contact("см. (linkedin.com/in/abc).")
    assert c.target.endswith("abc")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest intake-bot/tests/test_detect_contact.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.domain.contact'`.

- [ ] **Step 3: Write the implementation**

`intake-bot/app/domain/contact.py`:
```python
"""Deterministic detection of (platform, target) from free vacancy text.

Priority order: telegram > email > linkedin > hh > wellfound. The first rule
that matches wins. Platform detection is rule-based on purpose: it decides where
the message is later sent, so it must not depend on an LLM guess.
"""
import re
from dataclasses import dataclass


@dataclass
class Contact:
    platform: str   # telegram | email | linkedin | hh | wellfound
    target: str     # @nick / t.me URL / email / profile or vacancy URL


# t.me / telegram.me links (scheme optional).
_TME_RE = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/\w{3,}", re.IGNORECASE)
# A Telegram @handle anchored to start-or-whitespace, so it never matches the
# "@" inside an email address (e.g. john@gmail.com).
_HANDLE_RE = re.compile(r"(?:^|\s)@(\w{4,})\b")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_LINKEDIN_RE = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/\S+", re.IGNORECASE)
_HH_RE = re.compile(r"(?:https?://)?(?:[\w.-]*\.)?hh\.ru/\S+", re.IGNORECASE)
_WELLFOUND_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:wellfound\.com|angel\.co)/\S+", re.IGNORECASE)

_TRAILING = ".,);]>\"'"


def _clean(url: str) -> str:
    return url.rstrip(_TRAILING)


def detect_contact(text: str) -> Contact | None:
    m = _TME_RE.search(text)
    if m:
        return Contact("telegram", _clean(m.group(0)))
    m = _HANDLE_RE.search(text)
    if m:
        return Contact("telegram", "@" + m.group(1))
    m = _EMAIL_RE.search(text)
    if m:
        return Contact("email", m.group(0))
    m = _LINKEDIN_RE.search(text)
    if m:
        return Contact("linkedin", _clean(m.group(0)))
    m = _HH_RE.search(text)
    if m:
        return Contact("hh", _clean(m.group(0)))
    m = _WELLFOUND_RE.search(text)
    if m:
        return Contact("wellfound", _clean(m.group(0)))
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest intake-bot/tests/test_detect_contact.py -v`
Expected: `11 passed`.

- [ ] **Step 5: Commit**

```bash
git add intake-bot/app/domain/contact.py intake-bot/tests/test_detect_contact.py
git commit -m "feat: add deterministic platform/target detection (detect_contact)"
```

---

## Task 3: `ExtractedLead` — nickname → target

**Files:**
- Modify: `intake-bot/app/domain/lead.py`
- Test: `intake-bot/tests/test_lead.py`

- [ ] **Step 1: Write the failing test**

`intake-bot/tests/test_lead.py`:
```python
from app.domain.lead import ExtractedLead


def test_lead_has_target_and_platform():
    lead = ExtractedLead(platform="email", target="r@x.com",
                         vacancy_context="Backend", raw_text="raw")
    assert lead.platform == "email"
    assert lead.target == "r@x.com"


def test_is_valid_requires_target():
    assert ExtractedLead("telegram", "@nick", "v", "r").is_valid() is True
    assert ExtractedLead("telegram", "  ", "v", "r").is_valid() is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest intake-bot/tests/test_lead.py -v`
Expected: FAIL (`__init__` got unexpected keyword `target`, or positional mismatch).

- [ ] **Step 3: Replace `intake-bot/app/domain/lead.py`**

```python
"""Domain entities. No external dependencies."""
from dataclasses import dataclass

# Fixed column order of the Google Sheet (Russian headers).
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

STATUS_NEW = "new"


@dataclass
class ExtractedLead:
    """Result of parsing a raw vacancy message."""

    platform: str          # telegram | email | linkedin | hh | wellfound
    target: str            # @nick / t.me / email / profile or vacancy URL (stored in «Цель»)
    vacancy_context: str   # role / conditions / salary, summarized
    raw_text: str          # original text the user sent

    def is_valid(self) -> bool:
        return bool(self.target.strip())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest intake-bot/tests/test_lead.py -v`
Expected: `2 passed`.

> NOTE: `extract_lead.py`, `sheets_repo.py`, and `webhook.py` still reference the old `nickname` field/signature and will be updated in Tasks 5–7. Do not touch them yet.

- [ ] **Step 5: Commit**

```bash
git add intake-bot/app/domain/lead.py intake-bot/tests/test_lead.py
git commit -m "feat: rename ExtractedLead.nickname to target, platform required"
```

---

## Task 4: `OpenAISummarizer` (summarize only)

**Files:**
- Modify (replace): `intake-bot/app/infrastructure/openai_client.py`
- Test: `intake-bot/tests/test_summarizer.py`

- [ ] **Step 1: Write the failing test**

`intake-bot/tests/test_summarizer.py`:
```python
from app.infrastructure.openai_client import OpenAISummarizer


class _Msg:
    def __init__(self, content): self.message = type("M", (), {"content": content})


class _Resp:
    def __init__(self, content): self.choices = [_Msg(content)]


class _FakeClient:
    def __init__(self, content=None, raise_exc=None):
        self._content = content
        self._raise = raise_exc
        self.chat = type("C", (), {"completions": self})()

    def create(self, **kwargs):
        if self._raise:
            raise self._raise
        return _Resp(self._content)


def test_summarize_returns_vacancy_context():
    client = _FakeClient(content='{"vacancy_context": "Backend, remote, Python"}')
    s = OpenAISummarizer("key", "model", client=client)
    assert s.summarize("any text") == "Backend, remote, Python"


def test_summarize_returns_empty_on_error():
    client = _FakeClient(raise_exc=RuntimeError("boom"))
    s = OpenAISummarizer("key", "model", client=client)
    assert s.summarize("any text") == ""


def test_summarize_returns_empty_on_bad_json():
    client = _FakeClient(content="not json")
    s = OpenAISummarizer("key", "model", client=client)
    assert s.summarize("any text") == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest intake-bot/tests/test_summarizer.py -v`
Expected: FAIL (`cannot import name 'OpenAISummarizer'`).

- [ ] **Step 3: Replace `intake-bot/app/infrastructure/openai_client.py`**

```python
"""OpenAI-backed summarizer: condenses a vacancy message into a short summary.

Contact detection is NOT done here (see app.domain.contact); this only produces
the vacancy_context text. Any failure returns "" so the lead is never lost.
"""
import json

from openai import OpenAI

_SYSTEM = (
    "Ты кратко суммируешь сообщения с вакансиями. Верни строго JSON "
    '{"vacancy_context": "..."} — роль, формат работы, условия и зарплата '
    "(если есть). Не добавляй контактов и ссылок, только суть вакансии."
)


class OpenAISummarizer:
    def __init__(self, api_key: str, model: str, client=None):
        self._client = client or OpenAI(api_key=api_key)
        self._model = model

    def summarize(self, raw_text: str) -> str:
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": raw_text},
                ],
            )
            data = json.loads(resp.choices[0].message.content)
            return (data.get("vacancy_context") or "").strip()
        except Exception:  # noqa: BLE001 — summarization is best-effort
            return ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest intake-bot/tests/test_summarizer.py -v`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add intake-bot/app/infrastructure/openai_client.py intake-bot/tests/test_summarizer.py
git commit -m "refactor: OpenAIExtractor -> OpenAISummarizer (vacancy summary only)"
```

---

## Task 5: `ExtractLeadFromText` orchestration

**Files:**
- Modify (replace): `intake-bot/app/application/extract_lead.py`
- Test: `intake-bot/tests/test_extract_lead.py`

- [ ] **Step 1: Write the failing test**

`intake-bot/tests/test_extract_lead.py`:
```python
import pytest

from app.application.extract_lead import ExtractLeadFromText
from app.domain.contact import Contact


class _FakeSummarizer:
    def __init__(self, text): self._text = text
    def summarize(self, raw): return self._text


class _FakeRepo:
    def __init__(self): self.saved = []
    def append_lead(self, lead): self.saved.append(lead); return 1


def _detector(result):
    return lambda text: result


def test_saves_lead_with_detected_platform_and_target():
    repo = _FakeRepo()
    uc = ExtractLeadFromText(_detector(Contact("linkedin", "linkedin.com/in/x")),
                             _FakeSummarizer("Backend role"), repo)
    lead = uc.execute("some vacancy text linkedin.com/in/x")
    assert lead.platform == "linkedin"
    assert lead.target == "linkedin.com/in/x"
    assert lead.vacancy_context == "Backend role"
    assert repo.saved == [lead]


def test_raises_when_no_contact():
    repo = _FakeRepo()
    uc = ExtractLeadFromText(_detector(None), _FakeSummarizer("x"), repo)
    with pytest.raises(ValueError, match="no_contact"):
        uc.execute("no contact here")
    assert repo.saved == []


def test_falls_back_to_raw_text_when_summary_empty():
    repo = _FakeRepo()
    raw = "Длинный текст вакансии " * 20
    uc = ExtractLeadFromText(_detector(Contact("email", "a@b.com")),
                             _FakeSummarizer(""), repo)
    lead = uc.execute(raw)
    assert lead.vacancy_context == raw.strip()[:280]
    assert len(lead.vacancy_context) <= 280
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest intake-bot/tests/test_extract_lead.py -v`
Expected: FAIL (old `ExtractLeadFromText` signature `(extractor, repo)` and uses `is_valid`/`nickname`).

- [ ] **Step 3: Replace `intake-bot/app/application/extract_lead.py`**

```python
"""Use-case: detect contact + summarize a raw vacancy message, then save a lead."""
from app.domain.lead import ExtractedLead

_FALLBACK_LEN = 280


class ExtractLeadFromText:
    def __init__(self, detector, summarizer, repo):
        # detector: callable(text) -> Contact | None
        # summarizer: object with .summarize(text) -> str
        # repo: object with .append_lead(ExtractedLead) -> int (row id)
        self._detect = detector
        self._summarizer = summarizer
        self._repo = repo

    def execute(self, raw_text: str) -> ExtractedLead:
        contact = self._detect(raw_text)
        if contact is None:
            raise ValueError("no_contact")
        summary = self._summarizer.summarize(raw_text)
        if not summary:
            summary = raw_text.strip()[:_FALLBACK_LEN]
        lead = ExtractedLead(
            platform=contact.platform,
            target=contact.target,
            vacancy_context=summary,
            raw_text=raw_text,
        )
        self._repo.append_lead(lead)
        return lead
```

- [ ] **Step 4: Run test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest intake-bot/tests/test_extract_lead.py -v`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add intake-bot/app/application/extract_lead.py intake-bot/tests/test_extract_lead.py
git commit -m "feat: ExtractLeadFromText detects contact and summarizes"
```

---

## Task 6: `sheets_repo` — pure `lead_to_row` + write target

**Files:**
- Modify: `intake-bot/app/infrastructure/sheets_repo.py`
- Test: `intake-bot/tests/test_sheets_row.py`

> The full `SheetsRepo` needs gspread/credentials; extract the row-building into a
> pure `lead_to_row` function and test that. `append_lead` calls it.

- [ ] **Step 1: Write the failing test**

`intake-bot/tests/test_sheets_row.py`:
```python
from app.domain.lead import ExtractedLead
from app.infrastructure.sheets_repo import lead_to_row


def test_lead_to_row_column_positions():
    lead = ExtractedLead(platform="linkedin", target="linkedin.com/in/x",
                         vacancy_context="Backend", raw_text="raw text")
    row = lead_to_row(lead, row_id=7, now="2026-06-14 10:00")
    assert row == [
        7,                    # id
        "2026-06-14 10:00",   # Дата добавления
        "raw text",           # Исходный текст
        "linkedin",           # Платформа
        "linkedin.com/in/x",  # Цель
        "Backend",            # Вакансия
        "",                   # Сообщение
        "new",                # Статус
        "",                   # Дата отправки
        "",                   # Заметка
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest intake-bot/tests/test_sheets_row.py -v`
Expected: FAIL (`cannot import name 'lead_to_row'`).

- [ ] **Step 3: Read `intake-bot/app/infrastructure/sheets_repo.py`**

Read the file to find the current `append_lead` method body (it builds a `row` list using `lead.nickname`). Note the exact imports at the top.

- [ ] **Step 4: Add `lead_to_row` and use it in `append_lead`**

At module level (after the imports / constants, before the `SheetsRepo` class), add:
```python
def lead_to_row(lead, row_id, now):
    """Build the positional sheet row for one lead (matches COLUMNS order)."""
    return [
        row_id,                  # id
        now,                     # Дата добавления
        lead.raw_text,           # Исходный текст
        lead.platform,           # Платформа
        lead.target,             # Цель
        lead.vacancy_context,    # Вакансия
        "",                      # Сообщение
        STATUS_NEW,              # Статус
        "",                      # Дата отправки
        "",                      # Заметка
    ]
```
Then change the body of `append_lead` so it builds the row via the helper. Replace the inline `row = [...]` literal with:
```python
        row = lead_to_row(lead, row_id, now)
```
Keep the rest of `append_lead` (`_ensure_header`, `_next_id`, `now` computation, `self._ws.append_row(...)`, `return row_id`) unchanged. Ensure `STATUS_NEW` is imported (it already is).

- [ ] **Step 5: Run test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest intake-bot/tests/test_sheets_row.py -v`
Expected: `1 passed`.

- [ ] **Step 6: Commit**

```bash
git add intake-bot/app/infrastructure/sheets_repo.py intake-bot/tests/test_sheets_row.py
git commit -m "feat: intake sheets_repo writes target via pure lead_to_row"
```

---

## Task 7: Webhook wiring + messages + README

**Files:**
- Modify: `intake-bot/api/webhook.py`
- Modify: `README.md`

> No unit test (serverless entrypoint, needs FastAPI/env). Verify with `py_compile`
> (checks syntax without importing FastAPI/openai) + a grep for leftovers.

- [ ] **Step 1: Read `intake-bot/api/webhook.py`**

Confirm the current imports block, `_build_use_case`, and the success/`ValueError` reply lines (they reference `OpenAIExtractor`, `ExtractLeadFromText(extractor, repo)`, and `lead.nickname`).

- [ ] **Step 2: Update imports**

Replace:
```python
from app.infrastructure.openai_client import OpenAIExtractor  # noqa: E402
```
with:
```python
from app.domain.contact import detect_contact  # noqa: E402
from app.infrastructure.openai_client import OpenAISummarizer  # noqa: E402
```

- [ ] **Step 3: Update `_build_use_case`**

Replace its body with:
```python
def _build_use_case() -> ExtractLeadFromText:
    summarizer = OpenAISummarizer(config.OPENAI_API_KEY, config.OPENAI_MODEL)
    return ExtractLeadFromText(detect_contact, summarizer, _build_repo())
```

- [ ] **Step 4: Update the success + no_contact replies**

Replace the success reply block:
```python
        lead = _build_use_case().execute(text)
        _reply(
            chat_id,
            f"✅ Сохранил лид\nКонтакт: {lead.nickname}\nВакансия: {lead.vacancy_context}",
        )
```
with:
```python
        lead = _build_use_case().execute(text)
        _reply(
            chat_id,
            f"✅ Сохранил лид\nПлатформа: {lead.platform}\nЦель: {lead.target}\n"
            f"Вакансия: {lead.vacancy_context}",
        )
```
And replace the `except ValueError:` reply line:
```python
        _reply(chat_id, "⚠️ Не нашёл @ник или t.me-ссылку в тексте. Добавь контакт и пришли снова.")
```
with:
```python
        _reply(
            chat_id,
            "⚠️ Не нашёл контакт. Пришли вакансию с одним из: @ник, t.me-ссылка, "
            "email, или ссылка LinkedIn / hh.ru / Wellfound.",
        )
```

- [ ] **Step 5: Verify the file compiles**

Run: `sender/.venv/Scripts/python.exe -m py_compile intake-bot/api/webhook.py`
Expected: no output (exit 0 = syntax OK).
Then: `grep -n "nickname\|OpenAIExtractor" intake-bot/api/webhook.py`
Expected: no output.

- [ ] **Step 6: Update README**

In `README.md`, find the intake-bot section and add a sentence (Russian, matching style): the bot now auto-detects the platform and target from the pasted text (Telegram @ник / t.me, email, LinkedIn / hh.ru / Wellfound links) and fills the «Платформа»/«Цель» columns; if no contact is found it asks the user to resend with a contact.

- [ ] **Step 7: Run the whole intake test suite**

Run: `sender/.venv/Scripts/python.exe -m pytest intake-bot/tests -q`
Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add intake-bot/api/webhook.py README.md
git commit -m "feat: wire intake webhook to platform detection + summarizer"
```

---

## Self-Review notes (for the implementer)

- **Spec coverage:** hybrid detect+summarize (T2,T4,T5); priority order + email-vs-telegram (T2); `ExtractedLead` target rename (T3); summarizer error → "" + raw-text fallback (T4,T5); sheets writes target (T6); webhook wiring + no_contact hint (T7); tests incl. priority and None (T2,T5). README (T7).
- **Type consistency:** `Contact(platform, target)` and `ExtractedLead(platform, target, vacancy_context, raw_text)` keyword order is used identically across T2–T6. `ExtractLeadFromText(detector, summarizer, repo)` matches the webhook wiring in T7. `OpenAISummarizer(api_key, model, client=None)` matches T4 and T7 (T7 omits `client`, using the real OpenAI).
- **No leftover old API:** T3 removes `nickname`; T5 removes old `(extractor, repo)` signature and `is_valid` call (validity now implied by detection returning a contact); T6/T7 remove the last `nickname` references. Grep in T7 Step 5 guards this for the webhook.
- **Known seam:** regex rules (handle length `{4,}`, URL trailing-punct stripping) are heuristic; tests pin the important cases. Telegram-before-email priority relies on the anchored handle regex — covered by `test_plain_email_is_not_telegram`.
```
