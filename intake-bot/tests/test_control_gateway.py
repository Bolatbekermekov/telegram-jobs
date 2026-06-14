import datetime as _dt

from app.infrastructure.control_gateway import is_stale, start_search_reply


def test_is_stale_blank_true():
    assert is_stale("", _dt.datetime(2026, 6, 15, 10, 0, 0), 180)


def test_is_stale_fresh_false():
    now = _dt.datetime(2026, 6, 15, 10, 0, 0)
    assert not is_stale("2026-06-15 09:59:00", now, 180)


def test_start_search_reply_online():
    msg = start_search_reply(online=True)
    assert "запус" in msg.lower()


def test_start_search_reply_offline_mentions_queue():
    msg = start_search_reply(online=False)
    assert "офлайн" in msg.lower() and "очеред" in msg.lower()
