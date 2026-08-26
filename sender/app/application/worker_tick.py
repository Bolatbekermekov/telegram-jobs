"""One iteration of the worker loop: heartbeat, then drain pending requests."""
from app.domain.search_request import REQ_RUNNING, REQ_DONE, REQ_ERROR


def worker_tick(control_repo, run_one) -> None:
    control_repo.touch()
    for req in control_repo.pending_requests():
        control_repo.mark(req.id, REQ_RUNNING)
        try:
            run_one(req)
            control_repo.mark(req.id, REQ_DONE)
        except Exception:  # noqa: BLE001 — a request never kills the loop
            # Сюда же приходит осознанный отказ по паузе (SearchPaused): `error`
            # в таблице значит «не выполнено», и это правда, а `done` соврало бы,
            # что поиск прошёл. Причину человеку присылают отдельно, в Telegram —
            # колонки под неё у запроса нет.
            control_repo.mark(req.id, REQ_ERROR)
