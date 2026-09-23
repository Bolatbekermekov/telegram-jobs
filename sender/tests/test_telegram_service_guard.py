"""Канал Telegram не пишет служебным аккаунтам даже по уже записанному лиду."""
import pytest

from app.domain.channel import ChannelError, OutreachContent
from app.infrastructure.channels.telegram import TelegramChannel


@pytest.mark.parametrize("target", ["https://t.me/tribute", "@Wallet", "t.me/BotFather"])
def test_refuses_service_account_before_touching_telegram(target):
    ch = TelegramChannel.__new__(TelegramChannel)  # без клиента: сеть не нужна
    with pytest.raises(ChannelError):
        ch.send(target, OutreachContent(body="hi"))
