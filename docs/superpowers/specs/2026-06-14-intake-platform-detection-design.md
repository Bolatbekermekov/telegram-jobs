# Intake platform/target auto-detection (sub-project A)

**Date:** 2026-06-14
**Status:** design approved, spec under review

## Context

The intake bot receives a free-text vacancy message in Telegram and saves a lead
row to Google Sheets. Today `OpenAIExtractor` pulls only a Telegram contact
(`@nick` / `t.me/...`) plus a vacancy summary, and the platform is hard-coded to
`"telegram"` (set as a default on `ExtractedLead`).

Sub-project B made the sender multi-platform and added "Платформа" + "Цель"
columns. Sub-project A closes the loop on the intake side: the user pastes a
vacancy whose contact may be a Telegram `@nick`/`t.me` link, an email, or a
LinkedIn / hh.ru / Wellfound URL, and the bot must detect the **platform** and
extract the correct **target** automatically.

Not in A (separate spec): vacancy-search automation for LinkedIn/Wellfound (C).

## Goal

Given raw pasted text, deterministically detect one `(platform, target)` and a
vacancy summary, then store a lead with the correct "Платформа"/"Цель".

Platforms (must match the sender's set): `telegram | email | linkedin | hh | wellfound`.

## Architecture

Hybrid: **deterministic regex** decides platform + target (high stakes — it
controls where the message is later sent); **OpenAI** only summarizes the vacancy.
The two steps are independent and separately testable.

Data flow:
```
Telegram msg → webhook → ExtractLeadFromText.execute(raw_text):
    contact = detect_contact(raw_text)        # pure regex
    if contact is None: raise ValueError("no_contact")
    vacancy_context = summarizer.summarize(raw_text)   # OpenAI (non-fatal)
    lead = ExtractedLead(platform=contact.platform, target=contact.target,
                         vacancy_context=..., raw_text=raw_text)
    repo.append_lead(lead)
→ sheet row with Платформа / Цель filled automatically
```

## Components

### `intake-bot/app/domain/contact.py` (new, pure)

```python
@dataclass
class Contact:
    platform: str   # telegram | email | linkedin | hh | wellfound
    target: str     # @nick / t.me URL / email / profile or vacancy URL

def detect_contact(text: str) -> Contact | None
```

Detection runs checks in a fixed **priority order** and returns the first match:

1. **telegram** — `t.me/<name>` / `telegram.me/<name>`, OR an `@handle` that is
   anchored to start-of-string or whitespace (so `john@gmail.com` is NOT matched
   as a Telegram handle). Handle: `[A-Za-z0-9_]{4,}`. Target stored as `@<handle>`
   (or the `t.me/...` URL as-is).
2. **email** — `[\w.+-]+@[\w-]+\.[\w.-]+`. Target = the address.
3. **linkedin** — URL containing `linkedin.com/` (any path: `/in/...`, `/jobs/...`).
   Target = the matched URL.
4. **hh** — URL `hh.ru/vacancy/<digits>` (also accept generic `hh.ru/...`).
   Target = the matched URL.
5. **wellfound** — URL containing `wellfound.com/` or `angel.co/`. Target = URL.

No match → returns `None`.

Rationale for telegram-before-email: the user's vacancies usually end with a
single intended contact; an anchored `@handle` regex avoids the email false
positive, so the priority is safe.

### `intake-bot/app/infrastructure/openai_client.py` (modify)

`OpenAIExtractor` becomes a summarizer: a method `summarize(raw_text) -> str`
that returns only the vacancy summary (role, format, conditions, salary). The
contact-extraction part of the system prompt is removed. On any OpenAI error,
`summarize` returns `""` (the use-case applies a fallback — see Error handling).
Class may be renamed to `OpenAISummarizer` for clarity; update the import in the
webhook/composition root accordingly.

### `intake-bot/app/domain/lead.py` (modify)

`ExtractedLead`: rename field `nickname` → `target`; `platform` no longer
defaults to `"telegram"` (it is always passed explicitly from detection).
`is_valid()` returns `bool(self.target.strip())`.

### `intake-bot/app/application/extract_lead.py` (modify)

`ExtractLeadFromText` takes a `detector` (callable/object exposing
`detect_contact`-style behavior), a `summarizer`, and `repo`. `execute` follows
the data-flow above. Raises `ValueError("no_contact")` when detection returns
`None`.

### `intake-bot/app/infrastructure/sheets_repo.py` (modify)

`append_lead` writes `lead.target` into "Цель" (replacing `lead.nickname`).
Column order is already correct from sub-project B; no header change.

### `intake-bot/api/webhook.py` (modify)

Catch `ValueError("no_contact")` and reply with a hint listing accepted contact
forms (@nick, t.me, email, LinkedIn / hh.ru / Wellfound link). Keep other
behavior unchanged.

## Error handling

- **No contact** → `ValueError("no_contact")` → bot replies hint; nothing saved.
- **OpenAI summarization failure** → non-fatal: `summarize` returns `""`; the
  use-case falls back to the first ~280 chars of `raw_text` as `vacancy_context`
  so a valid contact is never lost.

## Testing

- `detect_contact` (pure) — one test per platform; priority when multiple
  contacts present (telegram wins over email, email over linkedin, etc.);
  `john@gmail.com` detected as **email**, not telegram; bare text → `None`.
- `ExtractLeadFromText` — fake detector + fake summarizer + fake repo: stores
  lead with the detected platform/target and the summary; raises on `None`
  detection; uses raw-text fallback when summarizer returns `""`.

## Out of scope (A)

- Multiple leads per message (chose: one lead by priority).
- Saving `unknown`-platform rows (chose: reject with hint).
- Any vacancy-search automation (that is sub-project C).
