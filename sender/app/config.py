"""Configuration for the local sender. Reads the project-root .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

# Load the shared .env at the project root (telegram-jobs/.env).
# __file__ = telegram-jobs/sender/app/config.py -> parents[2] = telegram-jobs
_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.1")

TELEGRAM_API_ID = int(os.environ["TELEGRAM_API_ID"])
TELEGRAM_API_HASH = os.environ["TELEGRAM_API_HASH"]

# Path to the service-account JSON file; relative paths resolve against project root.
_sa = os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"]
GOOGLE_SERVICE_ACCOUNT_FILE = _sa if os.path.isabs(_sa) else str(_ROOT / _sa)
SHEET_ID = os.environ["SHEET_ID"]
SHEET_TAB = os.environ.get("SHEET_TAB", "Лист1")

CV_PATH = os.environ["CV_PATH"]
ATTACH_CV = os.environ.get("ATTACH_CV", "true").lower() == "true"

DAILY_SEND_LIMIT = int(os.environ.get("DAILY_SEND_LIMIT", "20"))
MIN_DELAY_SECONDS = int(os.environ.get("MIN_DELAY_SECONDS", "40"))
MAX_DELAY_SECONDS = int(os.environ.get("MAX_DELAY_SECONDS", "120"))

# Telethon session file lives next to the project root.
SESSION_PATH = str(_ROOT / "sender" / "userbot")
PROFILE_PATH = str(Path(__file__).resolve().parents[1] / "profile.md")
