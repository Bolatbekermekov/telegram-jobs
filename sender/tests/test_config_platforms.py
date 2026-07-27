from app.config import platform_enabled


def test_telegram_enabled_when_api_id_present():
    env = {"TELEGRAM_API_ID": "1", "TELEGRAM_API_HASH": "h"}
    assert platform_enabled("telegram", env) is True


def test_email_enabled_requires_host_and_user():
    assert platform_enabled("email", {"SMTP_HOST": "h", "SMTP_USER": "u"}) is True
    assert platform_enabled("email", {"SMTP_HOST": "h"}) is False


def test_unknown_platform_disabled():
    assert platform_enabled("nope", {}) is False


def test_hh_always_enabled_browser_login():
    # Browser login is interactive (make login_hh); no env vars required.
    assert platform_enabled("hh", {}) is True


def test_hh_state_path_configured():
    from app import config
    assert config.HH_STATE_PATH.endswith("hh_state.json")


def test_threads_always_enabled_browser_login():
    # Browser login is interactive (make login_threads); no env vars required.
    assert platform_enabled("threads", {}) is True


def test_threads_state_path_configured():
    from app import config
    assert config.THREADS_STATE_PATH.endswith("threads_state.json")
