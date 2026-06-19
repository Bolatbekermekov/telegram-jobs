from app.application.worker_tick import worker_tick
from app.domain.search_request import SearchRequest, REQ_DONE


class _FakeControl:
    def __init__(self, pending):
        self._pending = pending
        self.touched = False
        self.marked = []

    def touch(self):
        self.touched = True

    def pending_requests(self):
        return self._pending

    def mark(self, request_id, status):
        self.marked.append((request_id, status))


def test_worker_tick_heartbeats_and_processes_requests():
    control = _FakeControl([SearchRequest(id="1", platform="all", status="pending")])
    calls = []

    def run_one(req):
        calls.append(req.id)
        return 3

    worker_tick(control, run_one)
    assert control.touched
    assert calls == ["1"]
    assert ("1", "running") in control.marked
    assert ("1", REQ_DONE) in control.marked


def test_worker_tick_no_requests_still_heartbeats():
    control = _FakeControl([])
    worker_tick(control, lambda req: 0)
    assert control.touched
    assert control.marked == []
