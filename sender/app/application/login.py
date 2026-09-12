"""One-time interactive login for browser-based searchers (LinkedIn/Wellfound).

Each searcher's start() opens a browser window and, when no saved session
exists, waits for you to log in by hand and press Enter — then stores cookies.
After that the worker runs headless without prompting.
"""

# `make login` walks this list; wellfound goes last — its Chrome stays open (CDP).
LOGIN_ORDER = ["telegram", "linkedin", "hh", "remoteok", "jobicy", "threads",
               "wellfound"]


def telegram_session_file(session_path: str) -> str:
    """Telethon stores the session as <SESSION_PATH>.session."""
    return session_path + ".session"


def platforms_needing_login(has_session) -> list:
    """LOGIN_ORDER platforms whose session check came back False (or missing)."""
    return [p for p in LOGIN_ORDER if not has_session.get(p, False)]


def cdp_alive(cdp_url: str, timeout: float = 2.0) -> bool:
    """True when a Chrome with an open debug port answers on cdp_url."""
    import httpx

    try:
        return httpx.get(f"{cdp_url}/json/version", timeout=timeout).status_code == 200
    except Exception:  # noqa: BLE001 — no Chrome listening = no session
        return False


def login_all(searchers) -> list:
    """Run start()->stop() on each searcher. Returns names that logged in OK.

    One searcher failing neither stops the others nor leaks its browser.
    """
    done = []
    for s in searchers:
        try:
            s.start()
            done.append(getattr(s, "name", "?"))
        except Exception as exc:  # noqa: BLE001 — isolate per-platform failures
            print(f"⚠️ {getattr(s, 'name', '?')}: {exc}")
        finally:
            try:
                s.stop()
            except Exception:  # noqa: BLE001
                pass
    return done


# Сколько раз спрашиваем страницу, вошёл ли человек, и с каким шагом. Двести
# попыток по три секунды это десять минут. Пять оказалось в обрез живьём
# (2026-09-11): вход через Google уводит на его собственные экраны, и человек
# просто не успевает. Зависнуть навсегда всё равно не даёт.
_LOGIN_ATTEMPTS = 200
_LOGIN_INTERVAL_SECONDS = 3.0


def wait_for_login(logged_in, sleep=None, attempts: int = _LOGIN_ATTEMPTS,
                   interval: float = _LOGIN_INTERVAL_SECONDS) -> bool:
    """Ждать, пока страница сама не скажет, что мы вошли. True — дождались.

    Пришло на замену `input()`. Живьём 2026-09-11: запущенный без терминала на
    вводе (через `!` в Claude Code или любым неинтерактивным вызовом) вход падал
    с `EOFError` раньше, чем человек успевал набрать пароль в открывшемся окне, —
    окно оставалось висеть, сессия не сохранялась. Опрос заодно снимает ловушку
    «не закрывай окно до Enter»: помнить об этом больше не нужно.

    `sleep` поздним связыванием, а не значением по умолчанию: иначе тест,
    подменяющий time.sleep, всё равно спал бы по-настоящему — этот капкан здесь
    уже захлопывался на rate_limit.py.
    """
    import time

    sleep = sleep or time.sleep
    for attempt in range(attempts):
        try:
            if logged_in():
                return True
        except Exception:  # noqa: BLE001 — страница перезагружается под нами, это «ещё нет»
            pass
        if attempt < attempts - 1:
            sleep(interval)
    return False
