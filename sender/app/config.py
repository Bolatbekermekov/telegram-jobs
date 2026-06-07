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

# CV is taken from sender/cv/ (drop your PDF/txt there). An explicit CV_PATH in
# .env overrides this if the file exists (handy for a CV stored elsewhere).
CV_DIR = _ROOT / "sender" / "cv"


def _resolve_cv_path() -> str:
    override = os.environ.get("CV_PATH", "").strip()
    if override and Path(override).is_file():
        return override
    if CV_DIR.is_dir():
        files = sorted(
            p for p in CV_DIR.iterdir()
            if p.is_file() and p.suffix.lower() in (".pdf", ".txt")
        )
        if files:
            return str(files[0])
    raise FileNotFoundError(
        f"No CV found. Put your CV (PDF or txt) into {CV_DIR} "
        "or set CV_PATH in .env to its full path."
    )


CV_PATH = _resolve_cv_path()
ATTACH_CV = os.environ.get("ATTACH_CV", "true").lower() == "true"

DAILY_SEND_LIMIT = int(os.environ.get("DAILY_SEND_LIMIT", "20"))
MIN_DELAY_SECONDS = int(os.environ.get("MIN_DELAY_SECONDS", "40"))
MAX_DELAY_SECONDS = int(os.environ.get("MAX_DELAY_SECONDS", "120"))

# Telethon session file lives next to the project root.
SESSION_PATH = str(_ROOT / "sender" / "userbot")
PROFILE_PATH = str(Path(__file__).resolve().parents[1] / "profile.md")

# Fixed signature/contacts block appended to every message (NOT AI-generated, so
# links like LinkedIn are always correct). Fill sender/signature.txt; gitignored.
SIGNATURE_PATH = str(Path(__file__).resolve().parents[1] / "signature.txt")


def _read_signature() -> str:
    path = Path(SIGNATURE_PATH)
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


SIGNATURE_TEXT = _read_signature()
