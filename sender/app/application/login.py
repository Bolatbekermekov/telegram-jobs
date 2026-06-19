"""One-time interactive login for browser-based searchers (LinkedIn/Wellfound).

Each searcher's start() opens a browser window and, when no saved session
exists, waits for you to log in by hand and press Enter — then stores cookies.
After that the worker runs headless without prompting.
"""


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
