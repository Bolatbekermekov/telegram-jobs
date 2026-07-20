from app.infrastructure.channels.telegram import is_flood_error, normalize_target


def test_normalize_strips_at():
    assert normalize_target("@nick") == "nick"


def test_peer_flood_too_many_requests_is_flood():
    # PeerFloodError renders as "Too many requests (caused by SendMessageRequest)".
    assert is_flood_error(Exception("Too many requests (caused by SendMessageRequest)")) is True


def test_flood_wait_message_is_flood():
    assert is_flood_error(
        Exception("A wait of 300 seconds is required (caused by SendMessageRequest)")) is True


def test_ordinary_telegram_error_is_not_flood():
    assert is_flood_error(Exception('Cannot find any entity corresponding to "nick"')) is False


def test_normalize_extracts_from_tme_url():
    assert normalize_target("https://t.me/nick") == "nick"
    assert normalize_target("t.me/nick") == "nick"


def test_normalize_plain():
    assert normalize_target("nick") == "nick"


def test_channel_constructs_without_a_running_event_loop(tmp_path):
    """Regression: Telethon asks asyncio for a loop at construction time, and
    Python 3.14 raises instead of making one — so `make run` died before sending
    anything, with an error that looked like a broken login."""
    import asyncio

    from app.infrastructure.channels.telegram import TelegramChannel

    asyncio.set_event_loop(None)                      # exactly the state make run is in
    TelegramChannel(str(tmp_path / "sess"), 1, "hash")  # must not raise


def test_ensure_event_loop_keeps_an_existing_loop(tmp_path):
    """Must not replace a loop the caller already set up."""
    import asyncio

    from app.infrastructure.channels.telegram import _ensure_event_loop

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _ensure_event_loop()
    assert asyncio.get_event_loop() is loop
    loop.close()


class _FakeLoop:
    """Runs the coroutine for real, like Telethon's own loop does."""

    def run_until_complete(self, coro):
        import asyncio

        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


class _FakeClient:
    parse_mode = None

    def __init__(self, authorized):
        self.loop = _FakeLoop()
        self._authorized = authorized
        self.connected = False

    async def connect(self):
        self.connected = True

    async def is_user_authorized(self):
        return self._authorized


def _channel_with(authorized, monkeypatch, tmp_path):
    from app.infrastructure.channels import telegram as tg

    client = _FakeClient(authorized)
    monkeypatch.setattr(tg, "TelegramClient", lambda *a, **kw: client)
    return tg.TelegramChannel(str(tmp_path / "s"), 1, "h")


def test_start_raises_a_clear_error_on_a_revoked_session(monkeypatch, tmp_path):
    """Telethon's own start() would prompt `Please enter your phone` and block a
    terminal run forever; the channel must fail fast with what to do instead."""
    import pytest

    from app.domain.channel import ChannelUnavailable

    ch = _channel_with(False, monkeypatch, tmp_path)
    with pytest.raises(ChannelUnavailable, match="make login_telegram"):
        ch.start()


def test_start_connects_before_checking_authorisation(monkeypatch, tmp_path):
    import pytest

    from app.domain.channel import ChannelUnavailable

    ch = _channel_with(False, monkeypatch, tmp_path)
    with pytest.raises(ChannelUnavailable):
        ch.start()
    assert ch._client.connected is True


def test_start_succeeds_on_a_valid_session(monkeypatch, tmp_path):
    ch = _channel_with(True, monkeypatch, tmp_path)
    ch.start()          # must not raise
    assert ch._client.connected is True