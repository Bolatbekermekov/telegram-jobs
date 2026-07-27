"""Is a saved Threads Playwright state actually logged in?

Same trap as LinkedIn (see linkedin_session.py): Playwright saves whatever cookies
the context held, so a logged-out context yields a state file full of cookies with
no auth among them. Loading it browses as a guest, and Threads answers with a
login wall — which would surface as a per-lead failure instead of an obvious
"go log in".

Threads runs on Instagram's session, so the auth cookie is Instagram's `sessionid`.
`csrftoken`, `mid` and `ig_did` are present for guests too and are NOT a login
signal. VERIFY THIS NAME on the first real login (`make login_threads`, then look
at the cookies in the state file) — it is the one fact here that was reasoned from
Instagram's scheme rather than observed on a live Threads state.
"""
import json
import time
from pathlib import Path

_AUTH_COOKIE = "sessionid"


def has_valid_session(state_path: str, now: float | None = None) -> bool:
    """True when `state_path` holds a non-empty, unexpired `sessionid` cookie."""
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
