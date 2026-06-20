import datetime as dt

from app.application.auto_search import (
    due_auto_search, most_recent_slot, parse_times,
)

TIMES = [(12, 0), (16, 0), (22, 0)]


def test_parse_times():
    assert parse_times("12:00,16:00,22:00") == [(12, 0), (16, 0), (22, 0)]
    assert parse_times(" 9:30 , 18:00 ,") == [(9, 30), (18, 0)]


def test_most_recent_slot():
    day = dt.datetime(2026, 6, 21, 13, 0)
    assert most_recent_slot(TIMES, day) == dt.datetime(2026, 6, 21, 12, 0)
    assert most_recent_slot(TIMES, dt.datetime(2026, 6, 21, 11, 0)) is None
    assert most_recent_slot(TIMES, dt.datetime(2026, 6, 21, 23, 30)) == \
        dt.datetime(2026, 6, 21, 22, 0)


def test_does_not_fire_before_first_slot():
    now = dt.datetime(2026, 6, 21, 11, 0)
    assert due_auto_search(TIMES, None, now) is False


def test_fires_when_slot_crossed():
    last = dt.datetime(2026, 6, 21, 11, 59)   # worker booted at 11:59
    now = dt.datetime(2026, 6, 21, 12, 0, 30)  # clock crossed 12:00
    assert due_auto_search(TIMES, last, now) is True


def test_does_not_refire_same_slot():
    last = dt.datetime(2026, 6, 21, 12, 0, 30)  # already ran the 12:00 slot
    now = dt.datetime(2026, 6, 21, 12, 45)
    assert due_auto_search(TIMES, last, now) is False


def test_fires_again_at_next_slot():
    last = dt.datetime(2026, 6, 21, 12, 0, 30)
    now = dt.datetime(2026, 6, 21, 16, 1)
    assert due_auto_search(TIMES, last, now) is True


def test_startup_after_a_slot_does_not_catch_up():
    # Booted at 13:00 with last_run seeded to boot time; the 12:00 slot is skipped.
    boot = dt.datetime(2026, 6, 21, 13, 0)
    assert due_auto_search(TIMES, boot, boot) is False
