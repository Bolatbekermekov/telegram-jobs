import datetime as dt

from app.application.auto_search import should_auto_search


def test_runs_when_never_run_yet():
    now = dt.datetime(2026, 6, 20, 9, 0, 0)
    assert should_auto_search(None, now, every_hours=8) is True


def test_skips_before_interval_elapses():
    last = dt.datetime(2026, 6, 20, 9, 0, 0)
    now = last + dt.timedelta(hours=7, minutes=59)
    assert should_auto_search(last, now, every_hours=8) is False


def test_runs_after_interval_elapses():
    last = dt.datetime(2026, 6, 20, 9, 0, 0)
    now = last + dt.timedelta(hours=8)
    assert should_auto_search(last, now, every_hours=8) is True
