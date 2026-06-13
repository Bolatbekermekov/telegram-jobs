from app.config import platform_enabled


def test_telegram_enabled_when_api_id_present():
    env = {"TELEGRAM_API_ID": "1", "TELEGRAM_API_HASH": "h"}
    assert platform_enabled("telegram", env) is True


def test_email_enabled_requires_host_and_user():
    assert platform_enabled("email", {"SMTP_HOST": "h", "SMTP_USER": "u"}) is True
    assert platform_enabled("email", {"SMTP_HOST": "h"}) is False


def test_unknown_platform_disabled():
    assert platform_enabled("nope", {}) is False
