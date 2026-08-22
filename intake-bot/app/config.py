"""Configuration loaded from environment (.env locally, Vercel env vars in cloud)."""
import os

from dotenv import load_dotenv

load_dotenv()  # local .env; on Vercel the vars are injected and this is a no-op

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
# Summarising a pasted vacancy is extraction, not writing — the cheap tier is
# enough, and this runs on every message forwarded to the bot.
OPENAI_MODEL = os.environ.get("OPENAI_MODEL_CHEAP", "gpt-5.4-nano")
OPENAI_MAX_OUTPUT_TOKENS = int(os.environ.get("OPENAI_MAX_OUTPUT_TOKENS", "1000"))

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
# Optional shared secret to validate Telegram webhook calls.
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")

# Google credentials. Local: a path to the JSON file (GOOGLE_SERVICE_ACCOUNT_FILE).
# Cloud (public repo, e.g. Vercel): paste the JSON content into GOOGLE_SERVICE_ACCOUNT_JSON.
GOOGLE_SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
SHEET_ID = os.environ["SHEET_ID"]
SHEET_TAB = os.environ.get("SHEET_TAB", "Лист1")

# Вкладка «Кандидаты» боту больше не нужна: подтверждение найденного убрано
# 2026-08-22, поиск на ноуте кладёт лид сразу в основную вкладку. Настройки
# CANDIDATES_TAB и SHOW_BATCH (сколько карточек слать пачкой) ушли вместе с ним;
# у ноутбучной половины CANDIDATES_TAB остался — она читает старую вкладку ради
# дедупликации.
CONTROL_TAB = os.environ.get("CONTROL_TAB", "Команды")
HEARTBEAT_STALE_SECONDS = int(os.environ.get("HEARTBEAT_STALE_SECONDS", "180"))
