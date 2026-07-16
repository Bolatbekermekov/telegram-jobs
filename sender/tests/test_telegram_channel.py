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
