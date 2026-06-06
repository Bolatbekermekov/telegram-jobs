# Telegram Jobs — Outreach Automation (Design Spec)

Date: 2026-06-07
Status: Approved for planning

## 1. Goal

Personal tool for job-vacancy cold outreach on Telegram:

1. Throughout the week, from the phone, the user sends raw vacancy text to a Telegram bot.
2. The bot (always-on, cloud) uses OpenAI to extract the recipient `@nickname` / `t.me` URL
   and to structure the vacancy context, then appends a lead row to a Google Sheet.
3. At the end of the week, on the laptop, a local script reads `new` leads from the Sheet,
   uses OpenAI + the user's CV to generate a personalized DM, asks the user to
   approve/skip/edit each one, sends it from the user's own Telegram account, and updates
   the lead status back in the Sheet.

## 2. Hard constraints & risks

- Sending DMs "from my own name" to arbitrary users requires a **userbot** (Telethon),
  not a Bot API bot. This violates Telegram ToS and can get the account **banned**,
  especially for mass messaging. Mitigations: manual per-lead approval, randomized delays,
  daily cap, run from the user's home IP (never from a datacenter/cloud IP).
- The intake bot must be **always-on in the cloud** because the laptop is frequently off.
  Source of truth is the Google Sheet (cloud), so nothing is lost while the laptop sleeps.
- All secrets live only in `.env` (gitignored). Never committed, never hardcoded.

## 3. Architecture (two independent components)

```
Phone → vacancy text → [intake-bot: Telegram webhook + OpenAI extract] (cloud, always-on)
                                  ↓ append row (status=new)
                          Google Sheet  (cloud storage = source of truth)
                                  ↑ read new / update status
End of week: laptop on → [sender: Telethon userbot + OpenAI generate] (local, on demand)
   → per lead: show generated DM → user approve/skip/edit → send DM → status=sent/skipped
```

### Component 1 — intake-bot (cloud)
- Telegram webhook handler (FastAPI), deployed on **Vercel** (serverless, does not sleep on free tier).
- On message: call OpenAI to extract `nickname`/`url` + structured `vacancy_context`
  (role, conditions, salary) from free text; append a row to the Sheet with `status=new`.

### Component 2 — sender (local CLI)
- Python + **Telethon** (userbot under the user's account), run on the laptop on demand.
- Reads rows with `status=new`; for each, generates a personal message with OpenAI using the
  user's CV text + positioning profile + the lead's vacancy_context; shows it in the terminal;
  user chooses send / skip / edit; sends the DM **with the CV PDF attached**; updates
  `status` + `date_sent` in the Sheet.
- Account safety: randomized pauses between sends, configurable daily limit.

#### Message-generation strategy (positioning)
- The user is a **Fullstack developer** but also applies to **QA** roles.
- The generated message must: address HR/the contact, state interest in the specific vacancy,
  and frame the fullstack background as an **advantage** (e.g. for a QA role: "QA is genuinely
  interesting to me, and my dev/fullstack experience makes me a stronger QA").
- Tone/angle adapts to the vacancy type. The positioning rules live in an editable
  `sender/profile.md`, fed into the OpenAI prompt alongside the CV text.

#### CV handling (single file)
- One source file `cv.pdf` (default: `C:\Users\Bolatbek\Downloads\Bolatbek_Yermekov(FD).pdf`).
- Text is extracted via `pypdf` → passed to OpenAI for message generation.
- The same PDF is attached to the outgoing DM via Telethon.

## 4. Storage — Google Sheet

- Spreadsheet id: `1E8W0w7uIEU09sp2swth_nZebC4il2p1Zeq6Sr3J70pk`, tab `Лист1`.
- Columns (Russian headers, fixed order):
  `id | Дата добавления | Исходный текст | Ник/ссылка | Вакансия | Сообщение | Статус | Дата отправки | Заметка`
- Written by intake-bot: `id, Дата добавления, Исходный текст, Ник/ссылка, Вакансия, Статус=new`.
- Written by sender: `Сообщение, Статус, Дата отправки`. Manual: `Заметка`, `Статус=replied`.
- Statuses: `new` → `sent` | `skipped` | `failed` | `replied` (replied set manually).
- Access via service account (`gspread`); the sheet must be shared with the service-account email.

## 5. Stack

| Layer | intake-bot (cloud) | sender (local) |
|---|---|---|
| Language | Python 3.11+ | Python 3.11+ |
| Telegram | FastAPI webhook (Bot API) | Telethon (userbot) |
| AI | openai SDK (`OPENAI_MODEL`, default gpt-5.1) | openai SDK |
| Sheets | gspread | gspread |
| Run | Vercel serverless | CLI: `python -m app.interface.cli` |

## 6. Project layout (light clean architecture)

```
telegram-jobs/
├── intake-bot/
│   └── app/
│       ├── domain/          # Lead, Vacancy (no external deps)
│       ├── application/     # ExtractLeadFromText use-case
│       ├── infrastructure/  # openai_client.py, sheets_repo.py
│       └── interface/       # webhook.py (Vercel entrypoint)
├── sender/
│   └── app/
│       ├── domain/          # Lead, OutreachMessage
│       ├── application/     # GenerateMessage, SendOutreach use-cases
│       ├── infrastructure/  # telethon_client.py, sheets_repo.py, openai_client.py, cv_loader.py
│       └── interface/       # cli.py
├── docs/specs/
├── .env.example
├── .gitignore
└── README.md
```

Dependency rule: `interface → application → domain`; `infrastructure` plugged in behind interfaces,
so business logic (message generation, status rules) is testable without Telegram/Google.

## 7. Configuration (.env)

```
# OpenAI
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-5.1
# Telegram bot (intake)
TELEGRAM_BOT_TOKEN=...
# Telegram userbot (sender) — from https://my.telegram.org
TELEGRAM_API_ID=...
TELEGRAM_API_HASH=...
# Google Sheets
GOOGLE_SERVICE_ACCOUNT_JSON=./service_account.json
SHEET_ID=1E8W0w7uIEU09sp2swth_nZebC4il2p1Zeq6Sr3J70pk
SHEET_TAB=Лист1
# Sender safety
DAILY_SEND_LIMIT=20
MIN_DELAY_SECONDS=40
MAX_DELAY_SECONDS=120
# CV
CV_PATH=./cv.txt
```

## 8. Prerequisites the user must provide

- CV file (`cv.txt` / pdf) for message generation.
- `TELEGRAM_API_ID` + `TELEGRAM_API_HASH` from my.telegram.org (needed by Telethon).
- Share the Google Sheet with the service-account email (Editor).
- (Recommended) rotate all secrets that were shared in plaintext.

## 9. Out of scope (YAGNI)

- No two-way conversation / reply handling (user replies manually).
- No multi-account rotation, no proxy management.
- No web UI — terminal + Google Sheet only.
```
