"""Configuration loaded from environment (.env locally, Vercel env vars in cloud)."""
import os

from dotenv import load_dotenv

load_dotenv()  # local .env; on Vercel the vars are injected and this is a no-op

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.1")

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
# Optional shared secret to validate Telegram webhook calls.
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")

# Either a path to the JSON file OR the raw JSON string (used on Vercel).
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ["GOOGLE_SERVICE_ACCOUNT_JSON"]
SHEET_ID = os.environ["SHEET_ID"]
SHEET_TAB = os.environ.get("SHEET_TAB", "Лист1")
