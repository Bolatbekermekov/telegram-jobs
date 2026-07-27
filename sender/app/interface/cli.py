"""Interactive CLI: read `new` leads, generate, approve, send across platforms.

Leads are processed in sheet order (by id, top to bottom). At most one channel
is open at a time — browser channels and the Telegram userbot can't share a
process — so ChannelSwitcher stops the current channel and starts the next
whenever the platform changes between consecutive leads. Default mode asks
send/edit/skip per lead; AUTO_SEND=true sends automatically — except leads held
for a human by send_plan.hold_reason, which get `manual` instead of a send.
Per-platform daily limits and anti-ban delays apply.
"""
import random
import time

from app import config
from app.application.format_content import format_for_channel
from app.application.generate_message import (
    GenerateMessage, generate_body, subject_for,
)
from app.application.send_outreach import SendOutreach
from app.application.channel_switcher import ChannelSwitcher
from app.application.send_plan import (
    dm_fallback_reason,
    has_placeholder,
    hold_reason,
    skip_reason,
    unresolved_thread,
)
from app.domain.lead import (
    STATUS_FAILED,
    STATUS_MANUAL,
    STATUS_SENT,
    STATUS_SKIPPED,
)
from app.infrastructure.channels.registry import build_channel
from app.infrastructure.cv_loader import load_cv_text, load_text_file
from app.infrastructure.openai_client import OpenAIMessageGenerator
from app.infrastructure.sheets_repo import SheetsRepo

# Platforms the send loop can build a channel for. A platform missing here is a
# per-lead skip in skip_reason(), so forgetting to add one silently buries its leads.
_KNOWN = {"telegram", "linkedin", "hh", "email", "wellfound", "threads"}


def _prompt(msg: str) -> str:
    try:
        return input(msg).strip()
    except EOFError:
        return ""


def _show(message: str) -> None:
    print("\n--- СООБЩЕНИЕ ---\n" + message + "\n-----------------")


def _notify_done(platforms, added: int) -> None:
    """Best-effort Telegram ping after a search; no-op unless token+chat configured."""
    if not (config.TELEGRAM_BOT_TOKEN and config.NOTIFY_CHAT_ID):
        return
    from app.application.notify import search_done_message
    from app.infrastructure.telegram_notify import send_telegram
    send_telegram(config.TELEGRAM_BOT_TOKEN, config.NOTIFY_CHAT_ID,
                  search_done_message(list(platforms), added))


def _relevance_args() -> dict:
    """Kwargs that turn on AI relevance scoring in run_search, or {} when disabled."""
    if not config.RELEVANCE_ENABLED:
        return {}
    from app.infrastructure.cv_loader import load_text_file
    from app.infrastructure.openai_relevance import OpenAIRelevanceScorer
    return dict(
        scorer=OpenAIRelevanceScorer(config.OPENAI_API_KEY, config.OPENAI_MODEL_CHEAP,
                                     max_output_tokens=config.OPENAI_MAX_OUTPUT_TOKENS),
        profile=load_text_file(config.SEARCH_PROFILE_PATH),
        threshold=config.MATCH_THRESHOLD,
        max_jobs=config.MATCH_MAX_JOBS,
    )


def run() -> None:
    print("== telegram-jobs sender (multi-platform) ==")
    cv_text = load_cv_text(config.CV_PATH)
    profile_text = load_text_file(config.PROFILE_PATH)

    repo = SheetsRepo(config.GOOGLE_SERVICE_ACCOUNT_FILE, config.SHEET_ID, config.SHEET_TAB)
    generator = GenerateMessage(
        OpenAIMessageGenerator(config.OPENAI_API_KEY, config.OPENAI_MODEL,
                               max_output_tokens=config.OPENAI_MAX_OUTPUT_TOKENS),
        cv_text, profile_text, config.SIGNATURE_TEXT,
    )

    leads = repo.fetch_new_leads()
    if not leads:
        print("Нет новых лидов (статус 'new'). Выход.")
        return

    mode = "АВТО (без подтверждения)" if config.AUTO_SEND else "ручной"
    print(f"Новых лидов: {len(leads)}. Режим: {mode}.")

    sent_per_platform: dict[str, int] = {}
    rate_limited: set[str] = set()       # platforms that rate-limited us this run
    quit_requested = False
    gen_failures = 0                     # consecutive message-generation failures

    # Strict id order: walk leads top-to-bottom. ChannelSwitcher keeps a single
    # channel open and switches only when the platform changes (Telethon and
    # Playwright can't be live at once). skip_reason() runs before any channel
    # opens, so skipped leads never churn channels.
    switcher = ChannelSwitcher(lambda p: build_channel(p, config))
    try:
        for lead in leads:
            if quit_requested:
                break
            platform = lead.platform

            if platform in rate_limited:
                # Platform threw us off earlier this run (rate-limit) — leave its
                # remaining leads `new` (write no status) so the next run retries them,
                # matching the old grouped loop that `break`ed and left them unmarked.
                continue

            reason = skip_reason(lead, _KNOWN)
            if reason is not None:
                status, note = reason
                repo.mark_status(lead, status, note=note)
                print(f"⏭  Лид #{lead.lead_id} [{platform}]: {note} — пропуск.")
                continue

            if lead.platform == "threads":
                # og:description gave the intake the root post only; the rest of the
                # vacancy and the contact live in the author's self-replies, which
                # need a browser. Anonymous render: reading a public post must not
                # touch the saved session. This runs BEFORE the channel is opened —
                # resolving changes lead.platform, and opening first would raise a
                # Threads browser for a lead that should go out over Telegram.
                from app.application.resolve_threads_lead import resolve_threads_lead
                from app.infrastructure.openai_contact import OpenAIContactDetector
                from app.infrastructure.threads_session import has_valid_session
                from app.infrastructure.threads_thread import render_thread
                print("Читаю тред Threads...")
                thread_url = lead.target      # resolving replaces it with the contact
                lead, review = resolve_threads_lead(
                    lead, repo,
                    render=lambda u: render_thread(u, headless=config.BROWSER_HEADLESS),
                    # The writing model, not the cheap one: once per lead, and a
                    # wrong answer is a message to the wrong person.
                    llm=OpenAIContactDetector(
                        config.OPENAI_API_KEY, config.OPENAI_MODEL,
                        max_output_tokens=config.OPENAI_MAX_OUTPUT_TOKENS))
                if lead.platform != platform:
                    print(f"   контакт найден: {lead.platform} → {lead.target}")
                    platform = lead.platform
                elif unresolved_thread(lead.target):
                    # Still pointing at the post, so the thread never rendered and
                    # resolving handed the lead back untouched, writing no status.
                    # Leave it that way: `new` means the next run tries again, and
                    # that retry is worth protecting — a successful render may find a
                    # real contact in a self-reply and send over Telegram, never
                    # touching the DM fallback. There is nothing to send from the root
                    # post alone, and falling through would either kill the run (no
                    # session -> ChannelUnavailable -> SystemExit) or DM the author
                    # without the vacancy text. A lead already on the DM fallback
                    # points at a handle, not a post, so re-queueing it by hand works.
                    print(f"⏭  Лид #{lead.lead_id}: тред не прочитался — "
                          "оставляю 'new', повторю в следующем прогоне.")
                    continue
                else:
                    print(f"   контакта в треде нет, буду писать автору: {lead.target}")

                hold = hold_reason(config.AUTO_SEND, review=review,
                                   contact=f"{lead.platform} → {lead.target}",
                                   source_url=thread_url)
                if hold is not None:
                    # Checked before the channel opens and before the message is
                    # generated — nothing to generate for a lead we won't send.
                    # Also before the rate-limit re-test below: the hold has to be
                    # written now, because the row is already rewritten to an
                    # ordinary platform and the next run would raise no flag.
                    status, note = hold
                    repo.mark_status(lead, status, note=note)
                    print(f"✋ Лид #{lead.lead_id}: {note}")
                    continue

                if platform in rate_limited:
                    # Re-tested after resolving: the check at the top of the loop
                    # saw `threads`, and this lead is now telegram/email/hh. In a
                    # loop built around ban avoidance, a resolved lead must not be
                    # the one thing that walks past the guard. No status written —
                    # same as the guard above, it retries next run.
                    print(f"⏭  Лид #{lead.lead_id}: платформа '{platform}' "
                          "ограничила нас в этом прогоне — оставляю на следующий.")
                    continue

                gated = dm_fallback_reason(
                    platform, lambda: has_valid_session(config.THREADS_STATE_PATH),
                    author=lead.target, source_url=thread_url)
                if gated is not None:
                    # The lead is on the DM fallback and there is no burner session.
                    # Gated HERE, before the channel opens, precisely so start() is
                    # never reached: its ChannelUnavailable meets the handler below,
                    # which ends the whole run — correct for a channel that is meant
                    # to work, but this one has no session by default and may never
                    # get one. One contactless Threads lead must not cost every other
                    # platform's leads their run. Before generation too: nothing to
                    # pay OpenAI for on a message that cannot be sent.
                    status, note = gated
                    repo.mark_status(lead, status, note=note)
                    print(f"✋ Лид #{lead.lead_id}: {note}")
                    continue

            try:
                channel = switcher.for_platform(platform)
            except Exception as exc:  # noqa: BLE001
                # A channel that won't start is a setup problem (dead session, Chrome
                # not running, bad config) — never the lead's fault, it was never even
                # attempted. Write no status, so this lead and every lead after it stay
                # `new`. Stop the whole run: leads are walked in sheet-id order, so the
                # queue is interleaved across platforms and limping on would drain the
                # healthy ones while the broken session goes unnoticed.
                sent_so_far = sum(sent_per_platform.values())
                print(f"\n❌ Канал '{platform}' не поднялся: {exc}")
                print(f"   Лид #{lead.lead_id} и все следующие остаются 'new'.")
                print(f"   Отправлено до остановки: {sent_so_far}. По платформам: {sent_per_platform}")
                print(f"   Причина: {type(exc).__name__}. Если это протухшая сессия — "
                      "`make login`; иначе смотри сообщение выше.")
                raise SystemExit(1) from exc
            sender = SendOutreach(channel)

            print("\n" + "=" * 60)
            print(f"Лид #{lead.lead_id}  [{platform}]  →  {lead.target}")
            print(f"Вакансия: {lead.vacancy_context or lead.raw_text}")
            print("-" * 60)

            print("Генерирую сообщение...")
            body, gen_err = generate_body(generator, lead)
            if gen_err is not None:
                # Generation hit OpenAI/network — don't crash the run (row 82).
                # Leave the lead `new` and move on; bail after 3 in a row, since
                # that means OpenAI is down and every remaining lead would fail too.
                gen_failures += 1
                print(f"⚠️  #{lead.lead_id}: не смог сгенерировать сообщение "
                      f"({type(gen_err).__name__}). Оставляю 'new'.")
                if gen_failures >= 3:
                    print("🛑 OpenAI недоступен (3 ошибки подряд) — останавливаю прогон. "
                          "Остальные лиды остаются 'new'. Проверь сеть/квоту и запусти снова.")
                    break
                continue
            gen_failures = 0
            subject = subject_for(lead.vacancy_context or lead.raw_text)
            attachment = config.CV_PATH if config.ATTACH_CV else None
            content = format_for_channel(channel, body, subject, attachment)

            if config.AUTO_SEND and has_placeholder(content.body):
                # What the README has always promised for auto mode: a template
                # must not reach a live recruiter just because nobody was there to
                # read it. NO status — unlike a contact, the body is regenerated
                # from scratch every run, so `new` self-heals for free next time.
                print(f"⏭  Лид #{lead.lead_id}: в тексте остался [плейсхолдер] — "
                      "оставляю 'new', перегенерирую в следующий прогон.")
                continue

            if not config.AUTO_SEND:
                _show(content.body)
                if "[" in content.body:
                    # No editor in this loop (only s/k/q), so the advice has to be
                    # something the human can actually do: quit and re-run, because
                    # generate_body runs fresh every run and the next roll is free.
                    print("⚠️  Остался [плейсхолдер]. Редактора здесь нет: выйди по q "
                          "и запусти прогон заново — текст генерится с нуля.")
                choice = _prompt("[s]end / [k]skip / [q]uit: ").lower()
                if choice in ("k", "skip"):
                    repo.mark_status(lead, STATUS_SKIPPED)
                    print("⏭  Пропущено.")
                    continue
                if choice in ("q", "quit"):
                    print("Выход по запросу.")
                    quit_requested = True
                    break

            result = sender.execute(lead, content)
            if result.ok:
                repo.mark_sent(lead, content.body, STATUS_SENT)
                sent_per_platform[platform] = sent_per_platform.get(platform, 0) + 1
                print(f"✅ Отправлено [{platform}] "
                      f"(всего за прогон: {sent_per_platform[platform]}).")
                delay = random.randint(config.MIN_DELAY_SECONDS, config.MAX_DELAY_SECONDS)
                print(f"⏳ Пауза {delay} c (анти-бан)...")
                time.sleep(delay)
            elif result.invited:
                # A LinkedIn connection request carrying the cover letter went out.
                # It's the whole outreach — no CV, no follow-up after they accept —
                # so record it as a normal send (won't be retried).
                repo.mark_sent(lead, content.body, STATUS_SENT)
                sent_per_platform[platform] = sent_per_platform.get(platform, 0) + 1
                print(f"📨 Запрос на контакт с письмом отправлен [{platform}] "
                      f"(всего за прогон: {sent_per_platform[platform]}).")
                delay = random.randint(config.MIN_DELAY_SECONDS, config.MAX_DELAY_SECONDS)
                print(f"⏳ Пауза {delay} c (анти-бан)...")
                time.sleep(delay)
            elif result.manual:
                # Couldn't auto-apply (gate/unknown form); leave for a manual apply.
                repo.mark_status(lead, STATUS_MANUAL, note=result.error)
                print(f"✋ Нужен ручной отклик [{platform}]: {result.error}")
            elif result.rate_limited:
                repo.mark_status(lead, STATUS_SKIPPED, note=result.error or "rate-limited")
                rate_limited.add(platform)
                print(f"🛑 Платформа '{platform}' ограничила нас ({result.error or 'rate-limited'}) "
                      "— остальные её лиды оставляю на следующий прогон.")
            else:
                repo.mark_status(lead, STATUS_FAILED, note=result.error)
                print(f"❌ Ошибка отправки: {result.error}")
    finally:
        switcher.close()

    total = sum(sent_per_platform.values())
    print(f"\nГотово. Отправлено за сессию: {total}. По платформам: {sent_per_platform}")


def run_worker():
    """Always-on loop: heartbeat, drain «Команды», auto-search ~3×/day. Ctrl+C to stop."""
    import datetime as _dt
    import time

    import gspread
    from google.oauth2.service_account import Credentials

    from app import config
    from app.application.auto_search import due_auto_search, parse_times
    from app.application.run_search import run_search
    from app.application.worker_tick import worker_tick
    from app.domain.search_request import SEARCH_PLATFORMS, SearchRequest, platforms_for
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
    searchers = {p: build_searcher(p) for p in SEARCH_PLATFORMS}

    def run_one(req):
        plats = platforms_for(req.platform)
        added = run_search(
            plats, searchers, candidates,
            keywords=config.SEARCH_KEYWORDS, location=config.SEARCH_LOCATION,
            limit=config.SEARCH_LIMIT_PER_PLATFORM,
            on_error=lambda p, e: print(f"⚠️ {p}: {e}"),
            **_relevance_args(),
        )
        _notify_done(plats, added)
        return added

    tz = _dt.timezone(_dt.timedelta(hours=config.AUTO_SEARCH_TZ_OFFSET))
    times = parse_times(config.AUTO_SEARCH_TIMES)
    last_auto = _dt.datetime.now(tz)  # seed with boot time so startup never fires
    print("worker started; polling every", config.WORKER_POLL_SECONDS, "s")
    print(f"auto-search scheduled at {config.AUTO_SEARCH_TIMES} (UTC+{config.AUTO_SEARCH_TZ_OFFSET})")
    while True:
        try:
            worker_tick(control, run_one)
            now = _dt.datetime.now(tz)
            if due_auto_search(times, last_auto, now):
                print(f"auto-search {now:%Y-%m-%d %H:%M} (UTC+{config.AUTO_SEARCH_TZ_OFFSET}): all platforms")
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
    from pathlib import Path

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
    if "hh" in platforms and not Path(config.HH_STATE_PATH).exists():
        # Manual run: log in interactively now instead of failing with a hint.
        # (The worker never gets here — it builds its searchers itself.)
        run_login_hh()
    searchers = {p: build_searcher(p) for p in platforms}
    print(f"Ищу вакансии: {', '.join(platforms)}...")
    added = run_search(
        platforms, searchers, candidates,
        keywords=config.SEARCH_KEYWORDS, location=config.SEARCH_LOCATION,
        limit=config.SEARCH_LIMIT_PER_PLATFORM,
        on_error=lambda p, e: print(f"⚠️ {p}: {e}"),
        **_relevance_args(),
    )
    print(f"Готово. Новых кандидатов записано: {added}.")
    _notify_done(platforms, added)


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


def run_login_hh():
    """Log in to hh.ru in the user's REAL Chrome, then export the session.

    hh.ru's anti-fraud blocks the login request (the SMS send) in any browser
    we launch through automation — the page opens, the submit spins forever.
    So the user logs in by hand in a real Chrome started with a debug port,
    and we pull the cookies over CDP into HH_STATE_PATH. Search and send then
    reuse the saved session silently; this Chrome may be closed afterwards.
    """
    import subprocess
    from pathlib import Path

    from app.infrastructure.search.wellfound_search import build_chrome_debug_args

    if Path(config.HH_STATE_PATH).exists():
        print(f"✅ Сессия hh.ru уже есть ({config.HH_STATE_PATH}). "
              "Удали этот файл, если хочешь перелогиниться.")
        return

    args = build_chrome_debug_args(
        config.HH_CHROME_PROFILE, config.HH_CDP_PORT, "https://hh.ru/account/login")
    print("Открываю твой Chrome для входа в hh.ru...")
    try:
        subprocess.Popen([config.CHROME_PATH, *args])
    except FileNotFoundError:
        print(f"❌ Не нашёл Chrome по пути {config.CHROME_PATH}. "
              f"Укажи его в переменной CHROME_PATH.")
        return

    print("\n1) Залогинься в hh.ru в открывшемся Chrome (телефон → SMS-код).")
    input("2) Когда увидишь себя залогиненным — вернись сюда и нажми Enter...")

    try:
        from patchright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(config.HH_CDP_URL)
            ctx = browser.contexts[0] if browser.contexts else None
            if ctx is None:
                print("⚠️ Не нашёл открытую вкладку Chrome. Запусти команду снова.")
                return
            cookie_names = {c["name"] for c in ctx.cookies("https://hh.ru")}
            if "hhtoken" not in cookie_names:
                print("⚠️ Похоже, вход не завершён (нет куки hhtoken). "
                      "Дологинься в Chrome и запусти `make login_hh` снова.")
                browser.close()  # disconnect only — leaves Chrome running
                return
            ctx.storage_state(path=config.HH_STATE_PATH)
            browser.close()  # disconnect only — leaves Chrome running
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️ Не смог забрать сессию по CDP: {exc}")
        return

    print(f"✅ Сессия сохранена в {config.HH_STATE_PATH}. Этот Chrome можно закрыть.")


def run_login_threads():
    """One-time interactive Threads login; saves the browser session to a file.

    Use a SEPARATE (burner) Instagram account: Threads runs on Instagram, and a
    disabled Instagram disables its Threads profile automatically.

    Only the DM fallback needs this session. Reading a thread to find the real
    contact is anonymous (infrastructure/threads_thread.py), so skipping this
    login costs nothing until a thread turns out to carry no contact at all.
    """
    from playwright.sync_api import sync_playwright

    saved = False
    # `with`, and the session pull guarded, the same way run_login_hh and
    # run_login_wellfound do it. Not defensive padding: the natural thing to do
    # once you are logged in is to CLOSE the window, and then storage_state()
    # raises on a dead context. Unguarded that is a raw Playwright traceback on
    # top of a login that actually WORKED, with the browser and the driver both
    # left running — and it is the first thing the human does after creating the
    # burner account, so it is the worst possible place to be unhelpful.
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        try:
            context = browser.new_context()
            context.new_page().goto("https://www.threads.com/login")
            print("Войди в Threads в открывшемся окне (через отдельный "
                  "Instagram-аккаунт), затем нажми Enter здесь...")
            input()
            try:
                context.storage_state(path=config.THREADS_STATE_PATH)
                saved = True
            except Exception as exc:  # noqa: BLE001
                # Nothing to recover: the cookies live in that browser context and
                # a closed window takes them with it. Say so, instead of a stack
                # trace that reads like the login itself failed.
                print(f"⚠️ Не смог забрать сессию из браузера: {exc}")
                print("   Скорее всего окно закрыли до того, как ты нажал Enter — "
                      "куки живут внутри него, и после закрытия взять их уже "
                      "неоткуда. Запусти `make login_threads` ещё раз и НЕ закрывай "
                      "окно, пока не нажмёшь Enter здесь.")
        finally:
            try:
                browser.close()
            except Exception:  # noqa: BLE001 — already gone is the normal case here
                pass

    if not saved:
        return

    # A saved state is not a session: Playwright stores whatever cookies the
    # context held, and a logged-out context yields a file with no auth in it.
    from app.infrastructure.threads_session import has_valid_session
    if has_valid_session(config.THREADS_STATE_PATH):
        print(f"✅ Сессия Threads сохранена: {config.THREADS_STATE_PATH}")
    else:
        print("⚠️ Файл сохранён, но живого `sessionid` в нём нет — вход не удался. "
              "Проверь, что действительно залогинился, и повтори.")


def run_login_all():
    """One command: log in to every platform, skipping ones with a live session.

    Telegram runs the QR script in a subprocess (its own asyncio flow); wellfound
    goes last because its Chrome must stay open for CDP.
    """
    import subprocess
    import sys
    from pathlib import Path

    from app.application.login import (
        LOGIN_ORDER,
        cdp_alive,
        platforms_needing_login,
        telegram_session_file,
    )

    from app.infrastructure.linkedin_session import has_valid_session
    from app.infrastructure.threads_session import (
        has_valid_session as threads_has_valid_session,
    )

    has_session = {
        "telegram": Path(telegram_session_file(config.SESSION_PATH)).exists(),
        # A LinkedIn state file can exist yet be logged out (no live li_at); that
        # is not a session to skip — re-login instead.
        "linkedin": has_valid_session(config.LINKEDIN_STATE_PATH),
        "hh": Path(config.HH_STATE_PATH).exists(),
        # Same trap as LinkedIn: a state file without a live sessionid is a guest.
        "threads": threads_has_valid_session(config.THREADS_STATE_PATH),
        "wellfound": cdp_alive(config.WELLFOUND_CDP_URL),
    }
    todo = platforms_needing_login(has_session)
    for p in LOGIN_ORDER:
        if p not in todo:
            print(f"✅ {p}: сессия уже есть, пропускаю.")
    if not todo:
        print("Все платформы уже залогинены.")
        return

    def _login_telegram():
        qr_script = Path(__file__).resolve().parents[2] / "qr_login.py"
        subprocess.call([sys.executable, str(qr_script)])

    actions = {"telegram": _login_telegram, "linkedin": run_login_browser,
               "hh": run_login_hh, "threads": run_login_threads,
               "wellfound": run_login_wellfound}
    for p in todo:
        print(f"\n🔑 {p}: вход...")
        try:
            actions[p]()
        except Exception as exc:  # noqa: BLE001 — one platform must not stop the rest
            print(f"⚠️ {p}: {exc}")
    print(f"\nГотово. Логин выполнялся для: {', '.join(todo)}.")


if __name__ == "__main__":
    run()
