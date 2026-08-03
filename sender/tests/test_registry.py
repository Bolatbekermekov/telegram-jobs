import pytest

from app.infrastructure.channels.registry import build_channel
from app.infrastructure.channels.email_channel import EmailChannel
from app.infrastructure.channels.headhunter import HeadHunterChannel
from app.infrastructure.channels.threads import ThreadsChannel
from app.infrastructure.channels.remoteok import RemoteOKChannel
from app.infrastructure.channels.wellfound import WellfoundChannel


class _Cfg:
    SMTP_HOST = "h"; SMTP_PORT = 587; SMTP_USER = "u"; SMTP_PASSWORD = "p"
    EMAIL_FROM_NAME = "Me"
    HH_STATE_PATH = "hh.json"
    TELEGRAM_API_ID = 1; TELEGRAM_API_HASH = "h"; SESSION_PATH = "s"
    LINKEDIN_STATE_PATH = "l.json"; WELLFOUND_STATE_PATH = "w.json"
    WELLFOUND_CDP_URL = "http://127.0.0.1:9222"; APPLY_DRY_RUN = True
    THREADS_STATE_PATH = "t.json"; REMOTEOK_STATE_PATH = "ro.json"
    EXTERNAL_APPLY_ENABLED = True; APPLY_PROFILE_PATH = "apply.yml"
    CV_PATH = "cv.pdf"; OPENAI_API_KEY = ""
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


def test_build_threads_channel_uses_the_burner_session():
    # The DM fallback still needs a channel object built for it: without this
    # branch a threads lead with no contact in its thread dies on ValueError,
    # which the send loop reads as a broken channel and stops the whole run.
    ch = build_channel("threads", _Cfg())
    assert isinstance(ch, ThreadsChannel)
    assert ch._state_path == "t.json"
    assert ch._headless is True


def test_build_remoteok_channel_uses_its_own_browser_and_the_apply_deps():
    """У RemoteOK нет Cloudflare, поэтому, в отличие от Wellfound, канал
    поднимает СВОЙ браузер с сохранённой сессией — воркеру не нужно открытое
    окно. И он обязан получить внешний автоотклик: своей формы у площадки нет,
    всё заполнение делает external_apply."""
    ch = build_channel("remoteok", _Cfg())
    assert isinstance(ch, RemoteOKChannel)
    assert ch._state_path == "ro.json"
    assert ch._headless is True
    assert ch._ext.get("fn") is not None


def test_unknown_platform_raises():
    with pytest.raises(ValueError):
        build_channel("myspace", _Cfg())
