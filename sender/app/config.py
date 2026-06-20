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

# If true, the sender skips the per-lead prompt and sends everything automatically
# (always send, then wait the random delay). False (default) = ask send/edit/skip per lead.
AUTO_SEND = os.environ.get("AUTO_SEND", "false").lower() == "true"

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

# --- Per-platform settings (all optional; a platform is enabled when configured) ---

# LinkedIn / Wellfound browser sessions
LINKEDIN_STATE_PATH = os.environ.get(
    "LINKEDIN_STATE_PATH", str(_ROOT / "sender" / "linkedin_state.json"))
WELLFOUND_STATE_PATH = os.environ.get(
    "WELLFOUND_STATE_PATH", str(_ROOT / "sender" / "wellfound_state.json"))
BROWSER_HEADLESS = os.environ.get("BROWSER_HEADLESS", "false").lower() == "true"

# Wellfound is behind Cloudflare Turnstile, which loops on any launched/headless
# browser. The interactive `wellfound` command instead launches the user's real
# Chrome with a debug port, lets them pass Cloudflare + log in by hand, then
# attaches over CDP and scrapes through that warm session.
CHROME_PATH = os.environ.get(
    "CHROME_PATH", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
WELLFOUND_CDP_PORT = int(os.environ.get("WELLFOUND_CDP_PORT", "9222"))
WELLFOUND_CDP_URL = os.environ.get(
    "WELLFOUND_CDP_URL", f"http://127.0.0.1:{WELLFOUND_CDP_PORT}")
WELLFOUND_CHROME_PROFILE = os.environ.get(
    "WELLFOUND_CHROME_PROFILE", str(_ROOT / "sender" / ".wellfound_chrome"))

# --- Vacancy search (sub-project C) ---
SEARCH_KEYWORDS = [
    k.strip() for k in os.environ.get("SEARCH_KEYWORDS", "internship,junior").split(",")
    if k.strip()
]
SEARCH_LOCATION = os.environ.get("SEARCH_LOCATION", "Worldwide")
SEARCH_LIMIT_PER_PLATFORM = int(os.environ.get("SEARCH_LIMIT_PER_PLATFORM", "15"))
SHOW_BATCH = int(os.environ.get("SHOW_BATCH", "7"))
WORKER_POLL_SECONDS = int(os.environ.get("WORKER_POLL_SECONDS", "60"))
HEARTBEAT_STALE_SECONDS = int(os.environ.get("HEARTBEAT_STALE_SECONDS", "180"))
# Worker fires an all-platform auto-search every N hours (8 ≈ 3×/day).
SEARCH_EVERY_HOURS = int(os.environ.get("SEARCH_EVERY_HOURS", "8"))
# After each search the worker pings this Telegram chat (needs the bot token).
# NOTIFY_CHAT_ID is your chat id with the bot (get it from @userinfobot).
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
NOTIFY_CHAT_ID = os.environ.get("NOTIFY_CHAT_ID", "")
# Recruiter-profile (DM) search is fragile/ban-prone; off by default.
LINKEDIN_PEOPLE_ENABLED = os.environ.get("LINKEDIN_PEOPLE_ENABLED", "false").lower() == "true"
# LinkedIn level filter (f_E): 1=Internship, 2=Entry/Junior, 3=Associate/Junior+.
# Empty = all levels. Recency f_TPR: r604800 = 7 days.
LINKEDIN_EXPERIENCE = os.environ.get("LINKEDIN_EXPERIENCE", "1,2,3")
LINKEDIN_POSTED_WITHIN = os.environ.get("LINKEDIN_POSTED_WITHIN", "r604800")

# AI relevance filtering of search results.
RELEVANCE_ENABLED = os.environ.get("RELEVANCE_ENABLED", "true").lower() == "true"
MATCH_THRESHOLD = int(os.environ.get("MATCH_THRESHOLD", "60"))
MATCH_MAX_JOBS = int(os.environ.get("MATCH_MAX_JOBS", "12"))  # per platform per run
SEARCH_PROFILE_PATH = os.environ.get(
    "SEARCH_PROFILE_PATH", str(_ROOT / "sender" / "search_profile.txt"))
# Human-like delay between scrape actions.
PACING_MIN_SECONDS = int(os.environ.get("PACING_MIN_SECONDS", "2"))
PACING_MAX_SECONDS = int(os.environ.get("PACING_MAX_SECONDS", "6"))
# Sheet tabs used for search coordination.
CANDIDATES_TAB = os.environ.get("CANDIDATES_TAB", "Кандидаты")
CONTROL_TAB = os.environ.get("CONTROL_TAB", "Команды")

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
