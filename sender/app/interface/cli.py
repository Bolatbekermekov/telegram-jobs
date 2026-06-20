"""Interactive CLI: read `new` leads, generate, approve, send across platforms.

One run walks every new lead, picks the channel for its platform, and sends.
Default mode asks send/edit/skip per lead. AUTO_SEND=true sends automatically.
Per-platform daily limits and anti-ban delays apply.
"""
import random
import time

from app import config
from app.application.format_content import format_for_channel
from app.application.generate_message import GenerateMessage, subject_for
from app.application.send_outreach import SendOutreach
from app.domain.lead import STATUS_FAILED, STATUS_SENT, STATUS_SKIPPED
from app.infrastructure.channels.registry import build_channel
from app.infrastructure.cv_loader import load_cv_text, load_text_file
from app.infrastructure.openai_client import OpenAIMessageGenerator
from app.infrastructure.sheets_repo import SheetsRepo

_KNOWN = {"telegram", "linkedin", "hh", "email", "wellfound"}


def _prompt(msg: str) -> str:
    try:
        return input(msg).strip()
    except EOFError:
        return ""


def _show(message: str) -> None:
    print("\n--- СООБЩЕНИЕ ---\n" + message + "\n-----------------")


def run() -> None:
    print("== telegram-jobs sender (multi-platform) ==")
    cv_text = load_cv_text(config.CV_PATH)
    profile_text = load_text_file(config.PROFILE_PATH)

    repo = SheetsRepo(config.GOOGLE_SERVICE_ACCOUNT_FILE, config.SHEET_ID, config.SHEET_TAB)
    generator = GenerateMessage(
        OpenAIMessageGenerator(config.OPENAI_API_KEY, config.OPENAI_MODEL),
        cv_text, profile_text, config.SIGNATURE_TEXT,
    )

    leads = repo.fetch_new_leads()
    if not leads:
        print("Нет новых лидов (статус 'new'). Выход.")
        return

    mode = "АВТО (без подтверждения)" if config.AUTO_SEND else "ручной"
    print(f"Новых лидов: {len(leads)}. Лимит/платформа: {config.DAILY_SEND_LIMIT}. Режим: {mode}.")

    channels: dict[str, object] = {}     # platform -> started channel
    sent_per_platform: dict[str, int] = {}
    blocked: set[str] = set()            # platforms stopped by rate-limit

    def _channel_for(platform: str):
        if platform in channels:
            return channels[platform]
        ch = build_channel(platform, config)
        print(f"Подключаюсь к каналу '{platform}'...")
        ch.start()
        channels[platform] = ch
        return ch

    try:
        for lead in leads:
            platform = lead.platform
            if platform not in _KNOWN:
                repo.mark_status(lead, STATUS_SKIPPED, note=f"unknown platform: {platform}")
                print(f"⏭  Лид #{lead.lead_id}: неизвестная платформа '{platform}', пропуск.")
                continue
            if platform in blocked:
                repo.mark_status(lead, STATUS_SKIPPED, note="platform rate-limited this run")
                continue
            if sent_per_platform.get(platform, 0) >= config.DAILY_SEND_LIMIT:
                repo.mark_status(lead, STATUS_SKIPPED, note="daily limit reached")
                continue

            print("\n" + "=" * 60)
            print(f"Лид #{lead.lead_id}  [{platform}]  →  {lead.target}")
            print(f"Вакансия: {lead.vacancy_context or lead.raw_text}")
            print("-" * 60)

            try:
                channel = _channel_for(platform)
            except Exception as exc:  # noqa: BLE001
                repo.mark_status(lead, STATUS_FAILED, note=f"channel start failed: {exc}")
                print(f"❌ Не удалось поднять канал '{platform}': {exc}")
                continue

            sender = SendOutreach(channel)
            print("Генерирую сообщение...")
            body = generator.execute(lead)
            subject = subject_for(lead.vacancy_context or lead.raw_text)
            attachment = config.CV_PATH if config.ATTACH_CV else None
            content = format_for_channel(channel, body, subject, attachment)

            if not config.AUTO_SEND:
                _show(content.body)
                if "[" in content.body:
                    print("⚠️  Остался [плейсхолдер] — заполни через edit перед отправкой.")
                choice = _prompt("[s]end / [k]skip / [q]uit: ").lower()
                if choice in ("k", "skip"):
                    repo.mark_status(lead, STATUS_SKIPPED)
                    print("⏭  Пропущено.")
                    continue
                if choice in ("q", "quit"):
                    print("Выход по запросу.")
                    return

            result = sender.execute(lead, content)
            if result.ok:
                repo.mark_sent(lead, content.body, STATUS_SENT)
                sent_per_platform[platform] = sent_per_platform.get(platform, 0) + 1
                print(f"✅ Отправлено [{platform}] "
                      f"({sent_per_platform[platform]}/{config.DAILY_SEND_LIMIT}).")
                delay = random.randint(config.MIN_DELAY_SECONDS, config.MAX_DELAY_SECONDS)
                print(f"⏳ Пауза {delay} c (анти-бан)...")
                time.sleep(delay)
            elif result.rate_limited:
                repo.mark_status(lead, STATUS_SKIPPED, note="rate-limited")
                blocked.add(platform)
                print(f"🛑 Платформа '{platform}' ограничила нас — останавливаю её на этот запуск.")
            else:
                repo.mark_status(lead, STATUS_FAILED, note=result.error)
                print(f"❌ Ошибка отправки: {result.error}")
    finally:
        for ch in channels.values():
            try:
                ch.stop()
            except Exception:  # noqa: BLE001
                pass
        total = sum(sent_per_platform.values())
        print(f"\nГотово. Отправлено за сессию: {total}. По платформам: {sent_per_platform}")


def run_worker():
    """Always-on loop: heartbeat, drain «Команды», auto-search ~3×/day. Ctrl+C to stop."""
    import time
    from datetime import datetime

    import gspread
    from google.oauth2.service_account import Credentials

    from app import config
    from app.application.auto_search import should_auto_search
    from app.application.run_search import run_search
    from app.application.worker_tick import worker_tick
    from app.domain.search_request import SearchRequest, platforms_for
    from app.infrastructure.candidates_repo import CandidatesRepo
    from app.infrastructure.control_repo import ControlRepo
    from app.infrastructure.search.registry import build_searcher

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(config.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=scopes)
    book = gspread.authorize(creds).open_by_key(config.SHEET_ID)
    main_ws = book.worksheet(config.SHEET_TAB)
    cand_ws = book.worksheet(config.CANDIDATES_TAB)
    ctrl_ws = book.worksheet(config.CONTROL_TAB)

    control = ControlRepo(ctrl_ws)
    candidates = CandidatesRepo(cand_ws, main_ws, config.SEARCH_LIMIT_PER_PLATFORM)
    searchers = {p: build_searcher(p) for p in ("linkedin", "wellfound")}

    def run_one(req):
        return run_search(
            platforms_for(req.platform), searchers, candidates,
            keywords=config.SEARCH_KEYWORDS, location=config.SEARCH_LOCATION,
            limit=config.SEARCH_LIMIT_PER_PLATFORM,
            on_error=lambda p, e: print(f"⚠️ {p}: {e}"),
        )

    print("worker started; polling every", config.WORKER_POLL_SECONDS, "s")
    last_auto = None
    while True:
        try:
            worker_tick(control, run_one)
            now = datetime.now()
            if should_auto_search(last_auto, now, config.SEARCH_EVERY_HOURS):
                print("auto-search: all platforms")
                run_one(SearchRequest(id="auto", platform="all", status="running"))
                last_auto = now
        except Exception as exc:  # noqa: BLE001 — survive transient sheet errors
            print("tick error:", exc)
        time.sleep(config.WORKER_POLL_SECONDS)


def run_search_once(platforms):
    """One-shot search across `platforms`, write candidates, then exit.

    Standalone process (does not touch the worker). Wellfound rides the warm
    Chrome from `make login_wellfound` via CDP; if it is closed, Wellfound is
    skipped and the other platforms still run.
    """
    import gspread
    from google.oauth2.service_account import Credentials

    from app.application.run_search import run_search
    from app.infrastructure.candidates_repo import CandidatesRepo
    from app.infrastructure.search.registry import build_searcher

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(config.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=scopes)
    book = gspread.authorize(creds).open_by_key(config.SHEET_ID)
    candidates = CandidatesRepo(
        book.worksheet(config.CANDIDATES_TAB), book.worksheet(config.SHEET_TAB),
        config.SEARCH_LIMIT_PER_PLATFORM)
    searchers = {p: build_searcher(p) for p in platforms}
    print(f"Ищу вакансии: {', '.join(platforms)}...")
    added = run_search(
        platforms, searchers, candidates,
        keywords=config.SEARCH_KEYWORDS, location=config.SEARCH_LOCATION,
        limit=config.SEARCH_LIMIT_PER_PLATFORM,
        on_error=lambda p, e: print(f"⚠️ {p}: {e}"),
    )
    print(f"Готово. Новых кандидатов записано: {added}.")


def run_login_browser():
    """Open the LinkedIn login window once and save the session.

    LinkedIn only (NOT Telegram — that's `make login_telegram`; NOT Wellfound —
    its Cloudflare loops on a launched browser, so it's handled interactively by
    `make wellfound`). Forces a visible browser (ignores BROWSER_HEADLESS) so you
    can actually log in. After this, the worker can run headless without prompting.
    """
    from app.application.login import login_all
    from app.infrastructure.search.linkedin_search import LinkedInSearcher

    searchers = [
        LinkedInSearcher(config.LINKEDIN_STATE_PATH, headless=False,
                         people_enabled=config.LINKEDIN_PEOPLE_ENABLED),
    ]
    print("Открываю окно входа в LinkedIn. Если сессия уже есть — окно просто закроется.")
    done = login_all(searchers)
    print(f"Готово. Сессии сохранены для: {', '.join(done) or '—'}")


def run_login_wellfound():
    """Open the user's real Chrome for a one-time Wellfound login.

    Wellfound's Cloudflare loops on any browser we launch headless/automated, so
    the user passes Cloudflare + logs in by hand here. The Chrome is left RUNNING
    with a debug port; every Wellfound search (worker / make search*) attaches to
    it over CDP. Does not scrape — that is `make search_wellfound` / the worker.
    """
    import subprocess

    from app.infrastructure.search.wellfound_search import build_chrome_debug_args

    args = build_chrome_debug_args(
        config.WELLFOUND_CHROME_PROFILE, config.WELLFOUND_CDP_PORT,
        "https://wellfound.com/login")
    print("Открываю твой Chrome для Wellfound...")
    try:
        subprocess.Popen([config.CHROME_PATH, *args])
    except FileNotFoundError:
        print(f"❌ Не нашёл Chrome по пути {config.CHROME_PATH}. "
              f"Укажи его в переменной CHROME_PATH.")
        return

    print("\n1) Пройди проверку Cloudflare и залогинься в Wellfound в открывшемся Chrome.")
    print("2) Дождись, пока загрузится твоя лента (не страница «Один момент…»).")
    input("3) Потом вернись сюда и нажми Enter — проверю сессию...")

    try:
        from patchright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(config.WELLFOUND_CDP_URL)
            ctx = browser.contexts[0] if browser.contexts else None
            page = ctx.pages[0] if ctx and ctx.pages else None
            title = page.title() if page else ""
            browser.close()  # disconnect only — leaves Chrome running
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ Не смог проверить сессию по CDP: {exc}. Chrome всё равно оставь открытым.")
        return

    if "момент" in title.lower() or "moment" in title.lower():
        print("⚠️ Похоже, ещё на проверке Cloudflare. Доделай вход и запусти команду снова.")
    else:
        print("✅ Сессия готова. Chrome НЕ закрывай — поиск Wellfound пойдёт через него.")


if __name__ == "__main__":
    run()
