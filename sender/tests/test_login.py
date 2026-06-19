from app.application.login import login_all


class _FakeSearcher:
    def __init__(self, name):
        self.name = name
        self.events = []

    def start(self):
        self.events.append("start")

    def stop(self):
        self.events.append("stop")


def test_login_all_starts_then_stops_each_in_order():
    a, b = _FakeSearcher("linkedin"), _FakeSearcher("wellfound")
    done = login_all([a, b])
    assert done == ["linkedin", "wellfound"]
    assert a.events == ["start", "stop"]
    assert b.events == ["start", "stop"]


def test_login_all_stops_even_if_start_fails_and_continues():
    boom = _FakeSearcher("linkedin")

    def explode():
        boom.events.append("start")
        raise RuntimeError("login window crashed")

    boom.start = explode
    ok = _FakeSearcher("wellfound")

    done = login_all([boom, ok])
    # the broken one is reported as not-done, but its session is still closed...
    assert "stop" in boom.events
    # ...and the next searcher still runs
    assert done == ["wellfound"]
    assert ok.events == ["start", "stop"]
