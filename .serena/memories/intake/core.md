# Intake architecture
- FastAPI Vercel webhook at intake-bot/api/webhook.py receives Telegram updates, commands, and candidate callbacks.
- Text/link intake detects the contact and platform deterministically, fetches supported vacancy pages when possible, asks OpenAI for a concise vacancy summary, then appends a `new` lead to the main Sheet.
- /start_search and per-platform search commands append requests to the Control tab; /show_vacancies reads Candidates; approve copies a candidate into the main leads tab.
- TELEGRAM_WEBHOOK_SECRET is optional in config; when non-empty, the endpoint checks Telegram's secret-token header.
- Google credentials support a local service-account file or inline JSON for Vercel.
- Synchronous external calls are made from the async webhook handler; keep serverless latency and replay/idempotency in mind when changing the flow.