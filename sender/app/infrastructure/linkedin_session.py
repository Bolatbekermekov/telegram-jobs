"""Is a saved LinkedIn Playwright state actually logged in?

A state file existing is not the same as a live session. Playwright saves
whatever cookies the context held, so a logged-out/guest context yields a file
with bcookie/lidc/JSESSIONID but no `li_at` — the member auth cookie. Loading
that state browses as a guest, and LinkedIn bounces every profile to the
authwall (no Message/Connect button), which surfaces downstream as a per-lead
"ни «Сообщение», ни «Контакт»" failure. Keying on `li_at` catches it up front.
"""
import json
import time
from pathlib import Path

# The member authentication cookie. Guest sessions never carry it; a logged-in
# one always does. `liap`/`JSESSIONID` are present even for guests, so they are
# not a login signal.
_AUTH_COOKIE = "li_at"


def _has_live_auth(cookies, now: float) -> bool:
    """Есть ли среди кук непустая, не истёкшая `li_at`.

    Одно определение на два места: файл сохранённой сессии и куки открытого окна
    входа. Разъедься они — окно считало бы входом то, что файл потом отвергнет.
    """
    for c in cookies or []:
        if c.get("name") != _AUTH_COOKIE or not (c.get("value") or "").strip():
            continue
        # -1/0 mark a session cookie (no expiry) — still usable from a saved state.
        expires = c.get("expires", -1)
        if expires in (-1, 0) or expires > now:
            return True
    return False


def has_valid_session(state_path: str, now: float | None = None) -> bool:
    """True when `state_path` holds a non-empty, unexpired `li_at` cookie."""
    p = Path(state_path)
    if not p.exists():
        return False
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError):
        return False
    return _has_live_auth(data.get("cookies", []), time.time() if now is None else now)


LOGIN_WAIT_SECONDS = 600
LOGIN_POLL_SECONDS = 3


def wait_for_login(context, wait_seconds: int = LOGIN_WAIT_SECONDS,
                   poll_seconds: int = LOGIN_POLL_SECONDS, sleep=None) -> bool:
    """Дождаться входа в открытом окне: в куках появилась живая `li_at`. True — дождались.

    Вместо `input()`. Из терминала без TTY — прогон агента, запуск в фоне — тот
    падал на EOFError мгновенно, `login_all` глотал исключение и закрывал окно, и
    новая сессия не сохранялась никогда. Опрос кук работает одинаково с TTY и без,
    а человеку нечего нажимать: окно само видит, что вход состоялся.

    Закрытое руками окно — тоже ответ: входа не будет, ждать дальше незачем.
    """
    sleep = sleep or time.sleep
    for _ in range(max(1, wait_seconds // max(1, poll_seconds))):
        try:
            cookies = context.cookies("https://www.linkedin.com")
        except Exception:  # noqa: BLE001 — окно закрыто: входа не будет
            return False
        if _has_live_auth(cookies, time.time()):
            return True
        sleep(poll_seconds)
    return False
