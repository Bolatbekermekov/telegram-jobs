import pytest

from app.infrastructure.channels.registry import build_channel
from app.infrastructure.channels.email_channel import EmailChannel
from app.infrastructure.channels.headhunter import HeadHunterChannel


class _Cfg:
    SMTP_HOST = "h"; SMTP_PORT = 587; SMTP_USER = "u"; SMTP_PASSWORD = "p"
    EMAIL_FROM_NAME = "Me"
    HH_ACCESS_TOKEN = "t"; HH_RESUME_ID = "r"
    TELEGRAM_API_ID = 1; TELEGRAM_API_HASH = "h"; SESSION_PATH = "s"
    LINKEDIN_STATE_PATH = "l.json"; WELLFOUND_STATE_PATH = "w.json"
    BROWSER_HEADLESS = True


def test_build_email_channel():
    assert isinstance(build_channel("email", _Cfg()), EmailChannel)


def test_build_hh_channel():
    assert isinstance(build_channel("hh", _Cfg()), HeadHunterChannel)


def test_unknown_platform_raises():
    with pytest.raises(ValueError):
        build_channel("myspace", _Cfg())
