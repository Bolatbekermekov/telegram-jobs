from app.infrastructure.channels.telegram import normalize_target


def test_normalize_strips_at():
    assert normalize_target("@nick") == "nick"


def test_normalize_extracts_from_tme_url():
    assert normalize_target("https://t.me/nick") == "nick"
    assert normalize_target("t.me/nick") == "nick"


def test_normalize_plain():
    assert normalize_target("nick") == "nick"
