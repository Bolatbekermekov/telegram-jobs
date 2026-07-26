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


def has_valid_session(state_path: str, now: float | None = None) -> bool:
    """True when `state_path` holds a non-empty, unexpired `li_at` cookie."""
    p = Path(state_path)
    if not p.exists():
        return False
    try:
        data = json.loads(p.read_text())
    except (OSError, ValueError):
        return False
    now = time.time() if now is None else now
    for c in data.get("cookies", []):
        if c.get("name") != _AUTH_COOKIE or not (c.get("value") or "").strip():
            continue
        # -1/0 mark a session cookie (no expiry) — still usable from a saved state.
        expires = c.get("expires", -1)
        if expires in (-1, 0) or expires > now:
            return True
    return False
