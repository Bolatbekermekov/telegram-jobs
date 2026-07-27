"""A state file existing is not the same as a live session — the lesson `li_at`
taught on LinkedIn, applied to Threads before it costs a run."""
import json
import time

from app.infrastructure.threads_session import has_valid_session


def _write(tmp_path, cookies):
    p = tmp_path / "threads_state.json"
    p.write_text(json.dumps({"cookies": cookies}))
    return str(p)


def test_missing_file_is_no_session(tmp_path):
    assert has_valid_session(str(tmp_path / "nope.json")) is False


def test_unparseable_file_is_no_session(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{not json")
    assert has_valid_session(str(p)) is False


def test_no_auth_cookie_is_no_session(tmp_path):
    """A logged-out context still saves csrftoken/mid — those are not a login."""
    path = _write(tmp_path, [{"name": "csrftoken", "value": "abc", "expires": -1},
                             {"name": "mid", "value": "xyz", "expires": -1}])
    assert has_valid_session(path) is False


def test_empty_auth_cookie_is_no_session(tmp_path):
    path = _write(tmp_path, [{"name": "sessionid", "value": "   ", "expires": -1}])
    assert has_valid_session(path) is False


def test_live_auth_cookie_is_a_session(tmp_path):
    path = _write(tmp_path, [{"name": "sessionid", "value": "s%3Aabc",
                              "expires": time.time() + 86400}])
    assert has_valid_session(path) is True


def test_session_cookie_without_expiry_counts(tmp_path):
    for expires in (-1, 0):
        path = _write(tmp_path, [{"name": "sessionid", "value": "s%3Aabc",
                                  "expires": expires}])
        assert has_valid_session(path) is True, expires


def test_expired_auth_cookie_is_no_session(tmp_path):
    path = _write(tmp_path, [{"name": "sessionid", "value": "s%3Aabc",
                              "expires": 1000}])
    assert has_valid_session(path, now=2000) is False
