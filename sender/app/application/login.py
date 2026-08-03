"""One-time interactive login for browser-based searchers (LinkedIn/Wellfound).

Each searcher's start() opens a browser window and, when no saved session
exists, waits for you to log in by hand and press Enter — then stores cookies.
After that the worker runs headless without prompting.
"""

# `make login` walks this list; wellfound goes last — its Chrome stays open (CDP).
LOGIN_ORDER = ["telegram", "linkedin", "hh", "remoteok", "threads", "wellfound"]


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
