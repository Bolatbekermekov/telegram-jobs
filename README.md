# telegram-jobs

Personal Telegram job-outreach automation.

- **`intake-bot/`** — always-on cloud Telegram bot. You forward raw vacancy text to it from
  your phone; it uses OpenAI to extract the `@nickname`/`t.me` contact + vacancy summary and
  appends a lead to a Google Sheet (`status=new`).
- **`sender/`** — local CLI you run on your laptop (e.g. end of week). It reads `new` leads,
  generates a personalized message with OpenAI (using your CV + `profile.md`), shows each one
  for approve/skip/edit, sends the DM **from your own account** (Telethon) with the CV PDF
  attached, and updates the status in the Sheet.

```
Phone → vacancy text → [intake-bot @Vercel + OpenAI] → Google Sheet (status=new)
End of week → [sender on laptop, Telethon] → reads Sheet → you approve → sends DM → status=sent
```

## ⚠️ Before anything: secrets & risks
- All secrets shared in chat are **compromised** — rotate them: OpenAI key, BotFather token
  (`/revoke`), Google service-account key, and the my.telegram.org `api_hash`.
- Secrets live only in `.env` and `service_account.json` — both are **gitignored**. Never commit them.
- The sender is a **userbot**: mass messaging violates Telegram ToS and can get your account
  **banned**. Keep `DAILY_SEND_LIMIT` low, keep the random delays, run from your home IP.

## One-time setup
1. Copy `.env.example` → `.env` and fill values.
2. **Add your own Google service-account key.** This project reads Google Sheets credentials
   from a JSON file path only (`GOOGLE_SERVICE_ACCOUNT_FILE`). Create a service account in
   Google Cloud Console, download its key, and save it as `service_account.json` in the
   project root. This file is **gitignored** and is **not** included in the repo — every user
   must provide their own.
3. Share your Google Sheet with the service-account email (the `client_email` from that JSON)
   as **Editor**, and set `SHEET_ID` / `SHEET_TAB` in `.env`.
4. Put your CV at the path in `CV_PATH` (PDF or txt).
5. Edit `sender/profile.md` to tune how messages position you.

## Run the sender (local)
```powershell
cd telegram-jobs\sender
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py
```
First run asks for your phone number + Telegram login code (creates `userbot.session`).
Per lead: `s`=send, `k`=skip, `e`=edit, `r`=regenerate, `q`=quit.

## Deploy the intake bot (Vercel)
Set **Root Directory = `intake-bot`** when importing the repo.

Env vars to add in the Vercel dashboard: `OPENAI_API_KEY`, `OPENAI_MODEL`, `TELEGRAM_BOT_TOKEN`,
`GOOGLE_SERVICE_ACCOUNT_JSON`, `SHEET_ID`, `SHEET_TAB`, and optionally `TELEGRAM_WEBHOOK_SECRET`.

**Credentials on the server (public repo):** `service_account.json` is gitignored and must
**never** be committed to a public repo. Instead, on Vercel set `GOOGLE_SERVICE_ACCOUNT_JSON`
to the **full JSON content** of your service-account key (open `service_account.json`, copy
everything, paste it as the value). The cloud component reads creds from this env var; locally
it keeps using the `GOOGLE_SERVICE_ACCOUNT_FILE` path. You do this once, not per deploy.

Then register the webhook (replace URL/token):
```powershell
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<your-app>.vercel.app/"
```
Now send a vacancy to your bot in Telegram — a `new` row should appear in the Sheet.
