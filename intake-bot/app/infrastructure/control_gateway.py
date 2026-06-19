"""Intake-side view of the «Команды» tab: queue search requests, read heartbeat."""
import datetime as _dt

CONTROL_COLUMNS = ["id", "platform", "status", "created_at", "done_at"]
_HEARTBEAT_CELL = "G1"
_TS = "%Y-%m-%d %H:%M:%S"


def is_stale(last_seen: str, now: _dt.datetime, threshold_seconds: int) -> bool:
    if not last_seen.strip():
        return True
    seen = _dt.datetime.strptime(last_seen.strip(), _TS)
    return (now - seen).total_seconds() > threshold_seconds


def start_search_reply(online: bool) -> str:
    if online:
        return "🔎 Запускаю поиск — кандидаты появятся через пару минут. Потом жми /show_vacancies."
    return ("⚠️ Ноут сейчас офлайн. Поставил поиск в очередь — выполню, как включишь ноут. "
            "Потом жми /show_vacancies.")


class ControlGateway:
    def __init__(self, control_ws):
        self._ws = control_ws

    def last_seen(self) -> str:
        return self._ws.acell(_HEARTBEAT_CELL).value or ""

    def is_worker_online(self, threshold_seconds: int) -> bool:
        return not is_stale(self.last_seen(), _dt.datetime.now(), threshold_seconds)

    def queue_search(self, platform: str = "all") -> None:
        if self._ws.row_values(1)[:5] != CONTROL_COLUMNS:
            self._ws.update("A1", [CONTROL_COLUMNS])
        row_id = max(len(self._ws.col_values(1)) - 1, 0) + 1
        now = _dt.datetime.now().strftime(_TS)
        self._ws.append_row([row_id, platform, "pending", now, ""],
                            value_input_option="USER_ENTERED")
