"""A saved LinkedIn state is 'valid' only when it still carries a live `li_at`.

The file existing is not enough: Playwright saves whatever cookies the context
held, and a logged-out/guest context has bcookie/lidc/JSESSIONID but no `li_at`.
Treating file-exists as logged-in makes every profile redirect to the authwall,
where there is no Message/Connect button — the lead then fails with
"ни «Сообщение», ни «Контакт»". These tests pin the real check.
"""
import json

from app.infrastructure.linkedin_session import has_valid_session

_FUTURE = 4_102_444_800.0   # 2100-01-01
_PAST = 1_000_000_000.0     # 2001-09-09


def _write(tmp_path, cookies):
    p = tmp_path / "linkedin_state.json"
    p.write_text(json.dumps({"cookies": cookies, "origins": []}))
    return str(p)


def test_missing_file_is_not_valid(tmp_path):
    assert not has_valid_session(str(tmp_path / "nope.json"))


def test_only_guest_cookies_is_not_valid(tmp_path):
    """The exact shape of the dead session that broke row 79."""
    path = _write(tmp_path, [
        {"name": "JSESSIONID", "value": "ajax:1", "expires": _FUTURE},
        {"name": "bcookie", "value": "v=2", "expires": _FUTURE},
        {"name": "lidc", "value": "b=x", "expires": _FUTURE},
    ])
    assert not has_valid_session(path)


def test_live_li_at_is_valid(tmp_path):
    path = _write(tmp_path, [{"name": "li_at", "value": "AQED...", "expires": _FUTURE}])
    assert has_valid_session(path)


def test_expired_li_at_is_not_valid(tmp_path):
    path = _write(tmp_path, [{"name": "li_at", "value": "AQED...", "expires": _PAST}])
    assert not has_valid_session(path, now=_PAST + 1)


def test_session_cookie_li_at_is_valid(tmp_path):
    """A `-1` expiry marks a session cookie — still usable in the saved state."""
    path = _write(tmp_path, [{"name": "li_at", "value": "AQED...", "expires": -1}])
    assert has_valid_session(path)


def test_empty_li_at_value_is_not_valid(tmp_path):
    path = _write(tmp_path, [{"name": "li_at", "value": "", "expires": _FUTURE}])
    assert not has_valid_session(path)


def test_malformed_json_is_not_valid(tmp_path):
    p = tmp_path / "linkedin_state.json"
    p.write_text("{not json")
    assert not has_valid_session(str(p))
