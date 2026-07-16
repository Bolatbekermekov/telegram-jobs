import pytest

from app.infrastructure.channels.registry import build_channel
from app.infrastructure.channels.email_channel import EmailChannel
from app.infrastructure.channels.headhunter import HeadHunterChannel
from app.infrastructure.channels.wellfound import WellfoundChannel


class _Cfg:
    SMTP_HOST = "h"; SMTP_PORT = 587; SMTP_USER = "u"; SMTP_PASSWORD = "p"
    EMAIL_FROM_NAME = "Me"
    HH_STATE_PATH = "hh.json"
    TELEGRAM_API_ID = 1; TELEGRAM_API_HASH = "h"; SESSION_PATH = "s"
    LINKEDIN_STATE_PATH = "l.json"; WELLFOUND_STATE_PATH = "w.json"
    WELLFOUND_CDP_URL = "http://127.0.0.1:9222"; APPLY_DRY_RUN = True
    BROWSER_HEADLESS = True


def test_build_email_channel():
    assert isinstance(build_channel("email", _Cfg()), EmailChannel)


def test_build_hh_channel():
    assert isinstance(build_channel("hh", _Cfg()), HeadHunterChannel)


def test_build_wellfound_channel_attaches_over_cdp_with_dry_run():
    ch = build_channel("wellfound", _Cfg())
    assert isinstance(ch, WellfoundChannel)
    assert ch._cdp_url == "http://127.0.0.1:9222"   # CDP attach, not storage_state
    assert ch._dry_run is True                       # honours APPLY_DRY_RUN


def test_unknown_platform_raises():
    with pytest.raises(ValueError):
        build_channel("myspace", _Cfg())
