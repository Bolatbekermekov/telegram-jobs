import pytest

from app.domain.channel import OutreachChannel
from app.infrastructure.channels.email_channel import EmailChannel
from app.infrastructure.channels.headhunter import HeadHunterChannel
from app.infrastructure.channels.linkedin import LinkedInChannel
from app.infrastructure.channels.telegram import TelegramChannel
from app.infrastructure.channels.wellfound import WellfoundChannel

_CHANNELS = [
    EmailChannel("h", 587, "u", "p", "Me"),
    HeadHunterChannel("hh.json", True),
    LinkedInChannel("l.json", True),
    WellfoundChannel("http://127.0.0.1:9222"),
    # TelegramChannel constructs a TelegramClient; skip instantiation, check class attrs.
]


@pytest.mark.parametrize("ch", _CHANNELS)
def test_satisfies_protocol(ch):
    assert isinstance(ch, OutreachChannel)
    assert ch.name in {"telegram", "linkedin", "hh", "email", "wellfound"}
    assert ch.body_limit is None or isinstance(ch.body_limit, int)
    assert isinstance(ch.needs_subject, bool)


def test_telegram_class_attrs():
    assert TelegramChannel.name == "telegram"
    assert TelegramChannel.needs_subject is False
