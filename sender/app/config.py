"""Configuration for the local sender. Reads the project-root .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

from app.domain.contacts import parse_contacts
from app.domain.cv_files import find_any_cv

# Load the shared .env at the project root (telegram-jobs/.env).
# __file__ = telegram-jobs/sender/app/config.py -> parents[2] = telegram-jobs
_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env")

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
# Writing model: the HR message and hh screening answers — a human reads these.
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.4-mini")
# Bulk model: relevance scoring runs on every job found on every platform on every
# search, so it dominates the bill. Scoring is classification (description in,
# 0-100 out), which is what the nano tier is built for.
OPENAI_MODEL_CHEAP = os.environ.get("OPENAI_MODEL_CHEAP", "gpt-5.4-nano")

# Cap the reply length. The vacancy text comes from a scraped third-party page, so
# without this an injected "write 10000 words" is billed in full.
OPENAI_MAX_OUTPUT_TOKENS = int(os.environ.get("OPENAI_MAX_OUTPUT_TOKENS", "2000"))

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
    # Ищем и в подпапках ролей тоже. Иначе, как только CV переедут в
    # sender/cv/<роль>/, верхний уровень опустеет и эта функция бросит
    # FileNotFoundError прямо на импорте конфига, уронив всё приложение.
    if CV_DIR.is_dir():
        found = find_any_cv(CV_DIR)
        if found is not None:
            return str(found)
    raise FileNotFoundError(
        f"No CV found. Put your CV (PDF or txt) into {CV_DIR} "
        "or set CV_PATH in .env to its full path."
    )


CV_PATH = _resolve_cv_path()
ATTACH_CV = os.environ.get("ATTACH_CV", "true").lower() == "true"
# hh has no PDF upload in the response form (it uses your online resume), but the
# vacancy CHAT does. When true, after responding hh also attaches the CV PDF in
# the chat. Fail-safe: if it can't, the application still counts as sent.
HH_ATTACH_CV_IN_CHAT = os.environ.get("HH_ATTACH_CV_IN_CHAT", "true").lower() == "true"

# How long to wait for the Submit button of hh's response popup. Only reached
# when the response has NOT already gone through (quick-apply is detected before
# this), so a long wait costs nothing on the normal path — it just gives a slow
# popup room to render instead of failing a vacancy that would have worked.
HH_SUBMIT_TIMEOUT_SECONDS = int(os.environ.get("HH_SUBMIT_TIMEOUT_SECONDS", "100"))

# If true, the sender skips the per-lead prompt and sends everything automatically
# (always send, then wait the random delay). False (default) = ask send/edit/skip per lead.
AUTO_SEND = os.environ.get("AUTO_SEND", "false").lower() == "true"

# Площадки, которые прогон не трогает: "linkedin" или "linkedin,hh".
# Лиды такой площадки остаются `new` и ждут снятия паузы — они НЕ становятся
# `skipped`, иначе прогон больше никогда их не поднял бы. Появилось после бана
# LinkedIn 2026-08-26: проверка приглашённых открывает LinkedIn первым делом в
# каждом прогоне, так что без этого выключателя нельзя было отправить даже то,
# что к LinkedIn отношения не имеет.
PAUSED_PLATFORMS = os.environ.get("PAUSED_PLATFORMS", "")

MIN_DELAY_SECONDS = int(os.environ.get("MIN_DELAY_SECONDS", "40"))
MAX_DELAY_SECONDS = int(os.environ.get("MAX_DELAY_SECONDS", "120"))

# Сколько дней не писать повторно тому же адресу, если вакансия ДРУГАЯ. Та же
# вакансия не отправляется повторно никогда, независимо от этого числа, —
# см. app/domain/outreach_history.py. Замер листа 2026-08-03: единственный
# законный повтор от одного рекрутёра случился через день, настоящие дубли —
# через 2, 9, 9 и 10 дней. Отсюда и раздельные правила.
DUPLICATE_WINDOW_DAYS = int(os.environ.get("DUPLICATE_WINDOW_DAYS", "5"))

# Сколько ждать ответа на запрос контакта в LinkedIn, прежде чем закрыть лид как
# `skipped`. Такое приглашение не двигается ничем, кроме чужого решения, поэтому
# без срока каждый прогон открывает его профиль заново — на 2026-08-03 самое
# старое (#79) проверялось так 17 дней подряд.
INVITE_MAX_WAIT_DAYS = int(os.environ.get("INVITE_MAX_WAIT_DAYS", "7"))

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

# Контакты отправителя, разобранные из подписи: один ник и один профиль на все
# площадки. Всё остальное (поля формы отклика, ответы модели, тело письма)
# приводится к ним — см. app/domain/contacts.py.
CONTACTS = parse_contacts(SIGNATURE_TEXT)

# --- Per-platform settings (all optional; a platform is enabled when configured) ---

# LinkedIn / Wellfound browser sessions
LINKEDIN_STATE_PATH = os.environ.get(
    "LINKEDIN_STATE_PATH", str(_ROOT / "sender" / "linkedin_state.json"))
WELLFOUND_STATE_PATH = os.environ.get(
    "WELLFOUND_STATE_PATH", str(_ROOT / "sender" / "wellfound_state.json"))
BROWSER_HEADLESS = os.environ.get("BROWSER_HEADLESS", "false").lower() == "true"

# Threads (Meta). Runs on an Instagram account, so automating it risks THAT
# account — use a separate (burner) Instagram, never your personal one: a
# disabled Instagram disables its Threads profile automatically.
THREADS_STATE_PATH = os.environ.get(
    "THREADS_STATE_PATH", str(_ROOT / "sender" / "threads_state.json"))

# --- External-apply autofill (LinkedIn jobs whose only route is a company ATS) ---
EXTERNAL_APPLY_ENABLED = os.environ.get("EXTERNAL_APPLY_ENABLED", "true").lower() == "true"
# true = fill the form but DO NOT click Submit (dry run for obkatka).
APPLY_DRY_RUN = os.environ.get("APPLY_DRY_RUN", "false").lower() == "true"
APPLY_PROFILE_PATH = os.environ.get(
    "APPLY_PROFILE_PATH", str(_ROOT / "sender" / "apply_profile.yml"))

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
# Список локаций для обхода. Одной строки было мало: вакансии в UAE, Турции или
# отдельных странах EU не искались никогда, а замер 2026-08-03 показал там живые
# пулы (UAE «ai engineer» — 68 за неделю, Turkey «vue developer» — 65).
# Пусто => берём одну SEARCH_LOCATION.
SEARCH_LOCATIONS = [
    s.strip() for s in os.environ.get("SEARCH_LOCATIONS", "").split(",") if s.strip()
]
# Потолок карточек на ОДИН запрос (слово × локация × страница). Раньше бюджет
# платформы делился между словами: 15 на 9 слов давало по одной вакансии на
# запрос, и всегда одну и ту же — LinkedIn сортирует по релевантности, а не по
# дате. 25 = ровно страница выдачи LinkedIn.
SEARCH_PER_KEYWORD = int(os.environ.get("SEARCH_PER_KEYWORD", "25"))
# Предохранитель на прогон: сколько карточек максимум собрать с платформы.
# Реально ограничивает не он, а MATCH_MAX_JOBS ниже — скорить всё собранное мы
# всё равно не будем.
SEARCH_LIMIT_PER_PLATFORM = int(os.environ.get("SEARCH_LIMIT_PER_PLATFORM", "250"))
# Сколько непросмотренных кандидатов держать в очереди на платформу. Раньше эту
# роль исполнял SEARCH_LIMIT_PER_PLATFORM, то есть одна настройка отвечала и за
# глубину поиска, и за длину очереди человеку.
CANDIDATES_PENDING_CAP = int(os.environ.get("CANDIDATES_PENDING_CAP", "60"))
SHOW_BATCH = int(os.environ.get("SHOW_BATCH", "7"))
WORKER_POLL_SECONDS = int(os.environ.get("WORKER_POLL_SECONDS", "60"))
HEARTBEAT_STALE_SECONDS = int(os.environ.get("HEARTBEAT_STALE_SECONDS", "180"))
# Worker auto-search runs at these fixed local times (HH:MM, comma-separated),
# in the timezone UTC+AUTO_SEARCH_TZ_OFFSET. Not on a rolling interval and not
# on worker startup. Default: 12:00 / 16:00 / 22:00 at UTC+5.
AUTO_SEARCH_TIMES = os.environ.get("AUTO_SEARCH_TIMES", "12:00,16:00,22:00")
AUTO_SEARCH_TZ_OFFSET = int(os.environ.get("AUTO_SEARCH_TZ_OFFSET", "5"))
# After each search the worker pings this Telegram chat (needs the bot token).
# NOTIFY_CHAT_ID is your chat id with the bot (get it from @userinfobot).
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
NOTIFY_CHAT_ID = os.environ.get("NOTIFY_CHAT_ID", "")
# Recruiter-profile (DM) search is fragile/ban-prone; off by default.
LINKEDIN_PEOPLE_ENABLED = os.environ.get("LINKEDIN_PEOPLE_ENABLED", "false").lower() == "true"
# LinkedIn level filter (f_E): 1=Internship, 2=Entry/Junior, 3=Associate/Junior+.
# Empty = all levels. Recency f_TPR: r604800 = 7 days.
# 4 (Mid-Senior) входит в значение по умолчанию намеренно: владелец профиля ищет
# и Junior, и Middle в каждой сфере, а search_profile.txt отдельной строкой
# говорит «Middle — ПОДХОДИТ». Без четвёрки Middle-вакансии не доходили бы даже
# до скоринга, и щель открывалась бы молча при потере .env.
LINKEDIN_EXPERIENCE = os.environ.get("LINKEDIN_EXPERIENCE", "1,2,3,4")
LINKEDIN_POSTED_WITHIN = os.environ.get("LINKEDIN_POSTED_WITHIN", "r604800")
# Формат работы (f_WT): 1=офис, 2=удалённо, 3=гибрид, пусто=любой. По умолчанию
# ПУСТО. Раньше здесь стояла константа f_WT=2, которую нельзя было выключить, и
# она отрезала 60–75% вакансий: замер 2026-08-03 за неделю дал «python
# developer» 1000+ удалённых против 3000+ всего, «ai engineer» — 2000+ против
# 8000+. Человеку, готовому к релокации, этот фильтр убирал именно то, что ему
# подходит.
LINKEDIN_WORKPLACE = os.environ.get("LINKEDIN_WORKPLACE", "")
# Сколько страниц выдачи проходить по каждому запросу (по 25 вакансий).
LINKEDIN_PAGES = int(os.environ.get("LINKEDIN_PAGES", "2"))
# Wellfound: у него в ссылке поиска тоже был вшит remote=true.
WELLFOUND_REMOTE_ONLY = os.environ.get(
    "WELLFOUND_REMOTE_ONLY", "false").lower() == "true"

# RemoteOK / Remotive (HTTP-only platforms — no browser, no login).
HTTP_USER_AGENT = os.environ.get(
    "HTTP_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
HTTP_TIMEOUT_SECONDS = int(os.environ.get("HTTP_TIMEOUT_SECONDS", "20"))
REMOTEOK_API_URL = os.environ.get("REMOTEOK_API_URL", "https://remoteok.com/api")
REMOTIVE_API_URL = os.environ.get(
    "REMOTIVE_API_URL", "https://remotive.com/api/remote-jobs")

# AI relevance filtering of search results.
RELEVANCE_ENABLED = os.environ.get("RELEVANCE_ENABLED", "true").lower() == "true"
MATCH_THRESHOLD = int(os.environ.get("MATCH_THRESHOLD", "60"))
# Сколько вакансий должно ДОЕХАТЬ до листа с одной площадки за прогон. Считает
# прошедших порог, а не потраченные оценки: до 2026-08-22 слот тратился на
# каждую оценку, и отвергнутые съедали бюджет целиком (замер: hh оценил 30,
# отверг 25, добавил 5 — и на этом остановился).
MATCH_MAX_JOBS = int(os.environ.get("MATCH_MAX_JOBS", "30"))
# Предохранитель к нему: сколько максимум вакансий разрешено ОЦЕНИТЬ за прогон
# на площадку. Нужен по цене — одна оценка это скачанное описание плюс вызов
# модели (замерено ~19 с на LinkedIn, ~38 с на hh), поэтому площадка, где всё
# ниже порога, без потолка сканировала бы всё найденное часами. 150 выбрано
# осознанно: при сегодняшней доле проходящих (5 из 30 на hh) это даёт реальный
# шанс набрать квоту, а в худшем случае стоит ~47 мин на LinkedIn и ~1,5 ч на hh.
MATCH_SCAN_LIMIT = int(os.environ.get("MATCH_SCAN_LIMIT", "150"))
SEARCH_PROFILE_PATH = os.environ.get(
    "SEARCH_PROFILE_PATH", str(_ROOT / "sender" / "search_profile.txt"))
# Локальная память о вакансиях, которые скорер уже отверг: без неё каждый
# прогон заново качал их описания и заново платил за скоринг, а сами они
# занимали весь бюджет MATCH_MAX_JOBS. Файл вспомогательный (gitignored):
# потерять его значит один раз переоценить отказников, не больше.
SCORED_OUT_PATH = os.environ.get(
    "SCORED_OUT_PATH", str(_ROOT / "sender" / ".scored_out.json"))
# Human-like delay between scrape actions.
PACING_MIN_SECONDS = int(os.environ.get("PACING_MIN_SECONDS", "2"))
PACING_MAX_SECONDS = int(os.environ.get("PACING_MAX_SECONDS", "6"))
# Sheet tabs used for search coordination.
CANDIDATES_TAB = os.environ.get("CANDIDATES_TAB", "Кандидаты")
CONTROL_TAB = os.environ.get("CONTROL_TAB", "Команды")

# HeadHunter (browser session; the applicant API was closed on 2025-12-15).
# Login happens in the user's REAL Chrome (anti-fraud blocks the SMS request
# in launched browsers): `make login_hh` starts Chrome with a debug port on a
# dedicated profile and exports the session over CDP into HH_STATE_PATH.
HH_STATE_PATH = os.environ.get(
    "HH_STATE_PATH", str(_ROOT / "sender" / "hh_state.json"))
HH_CDP_PORT = int(os.environ.get("HH_CDP_PORT", "9223"))  # 9222 is wellfound's
HH_CDP_URL = os.environ.get("HH_CDP_URL", f"http://127.0.0.1:{HH_CDP_PORT}")
HH_CHROME_PROFILE = os.environ.get(
    "HH_CHROME_PROFILE", str(_ROOT / "sender" / ".hh_chrome"))

# RemoteOK. Поиск идёт по открытому JSON API и аккаунта НЕ требует — сессия
# нужна только для отклика: кнопка Apply ведёт на /l/<id>, а тот уводит гостя
# на /sign-up?user_type=worker (проверено живьём 2026-08-03). Вход, как у hh,
# делается в настоящем Chrome (регистрация через Google в запущенном
# автоматикой браузере обычно блокируется), а сессия выгружается по CDP.
REMOTEOK_STATE_PATH = os.environ.get(
    "REMOTEOK_STATE_PATH", str(_ROOT / "sender" / "remoteok_state.json"))
REMOTEOK_CDP_PORT = int(os.environ.get("REMOTEOK_CDP_PORT", "9224"))  # 9222 wf, 9223 hh
REMOTEOK_CDP_URL = os.environ.get(
    "REMOTEOK_CDP_URL", f"http://127.0.0.1:{REMOTEOK_CDP_PORT}")
REMOTEOK_CHROME_PROFILE = os.environ.get(
    "REMOTEOK_CHROME_PROFILE", str(_ROOT / "sender" / ".remoteok_chrome"))

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
        return True  # browser login is interactive; always available
    if platform == "email":
        return bool(env.get("SMTP_HOST") and env.get("SMTP_USER"))
    if platform == "threads":
        return True  # browser login is interactive; always available
    return False
