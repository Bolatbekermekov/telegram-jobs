import datetime as _dt

from app.domain.search_request import REQ_PENDING
from app.infrastructure.control_repo import is_stale, request_to_row, CONTROL_COLUMNS


def test_control_columns():
    assert CONTROL_COLUMNS == ["id", "platform", "status", "created_at", "done_at"]


def test_request_to_row():
    row = request_to_row(row_id=2, platform="all", now="2026-06-15 10:00")
    assert row == [2, "all", REQ_PENDING, "2026-06-15 10:00", ""]


def test_is_stale_true_when_old():
    now = _dt.datetime(2026, 6, 15, 10, 0, 0)
    last = "2026-06-15 09:50:00"   # 600s ago
    assert is_stale(last, now, threshold_seconds=180)


def test_is_stale_false_when_fresh():
    now = _dt.datetime(2026, 6, 15, 10, 0, 0)
    last = "2026-06-15 09:59:00"   # 60s ago
    assert not is_stale(last, now, threshold_seconds=180)


def test_is_stale_true_when_blank():
    now = _dt.datetime(2026, 6, 15, 10, 0, 0)
    assert is_stale("", now, threshold_seconds=180)
