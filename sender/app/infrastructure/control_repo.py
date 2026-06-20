"""«Команды» tab: search requests + worker heartbeat.

Layout: row 1 = CONTROL_COLUMNS header; cell G1 holds the heartbeat timestamp.
Request rows live below the header.
"""
import datetime as _dt

from app.domain.search_request import REQ_PENDING, REQ_DONE, SearchRequest

CONTROL_COLUMNS = ["id", "platform", "status", "created_at", "done_at"]
_HEARTBEAT_CELL = "G1"
_TS = "%Y-%m-%d %H:%M:%S"


def request_to_row(row_id, platform: str, now: str) -> list:
    return [row_id, platform, REQ_PENDING, now, ""]


def is_stale(last_seen: str, now: _dt.datetime, threshold_seconds: int) -> bool:
    if not last_seen.strip():
        return True
    seen = _dt.datetime.strptime(last_seen.strip(), _TS)
    return (now - seen).total_seconds() > threshold_seconds


class ControlRepo:
    def __init__(self, worksheet):
        self._ws = worksheet

    def _ensure_header(self) -> None:
        if self._ws.row_values(1)[:5] != CONTROL_COLUMNS:
            self._ws.update("A1", [CONTROL_COLUMNS])

    def touch(self) -> None:
        self._ws.update(_HEARTBEAT_CELL, [[_dt.datetime.now().strftime(_TS)]])

    def last_seen(self) -> str:
        val = self._ws.acell(_HEARTBEAT_CELL).value
        return val or ""

    def add_request(self, platform: str) -> None:
        self._ensure_header()
        row_id = max(len(self._ws.col_values(1)) - 1, 0) + 1
        now = _dt.datetime.now().strftime(_TS)
        self._ws.append_row(request_to_row(row_id, platform, now),
                            value_input_option="USER_ENTERED", table_range="A1")

    def pending_requests(self) -> list:
        rows = self._ws.get_all_values()[1:]
        out = []
        for r in rows:
            if len(r) >= 3 and r[2] == REQ_PENDING:
                out.append(SearchRequest(id=r[0], platform=r[1], status=r[2]))
        return out

    def mark(self, request_id: str, status: str) -> None:
        col_id = 1
        ids = self._ws.col_values(col_id)
        for i, val in enumerate(ids[1:], start=2):  # skip header
            if val == request_id:
                self._ws.update_cell(i, CONTROL_COLUMNS.index("status") + 1, status)
                if status == REQ_DONE:
                    self._ws.update_cell(
                        i, CONTROL_COLUMNS.index("done_at") + 1,
                        _dt.datetime.now().strftime(_TS))
                return
