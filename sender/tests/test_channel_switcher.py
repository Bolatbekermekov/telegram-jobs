import pytest

from app.application.channel_switcher import ChannelSwitcher


class FakeChannel:
    def __init__(self, platform, log, raise_on_start=False, raise_on_stop=False):
        self.platform = platform
        self._log = log
        self._raise_on_start = raise_on_start
        self._raise_on_stop = raise_on_stop

    def start(self):
        if self._raise_on_start:
            raise RuntimeError(f"cannot start {self.platform}")
        self._log.append(("start", self.platform))

    def stop(self):
        if self._raise_on_stop:
            raise RuntimeError(f"stop boom {self.platform}")
        self._log.append(("stop", self.platform))


def _switcher(raise_start=(), raise_stop=()):
    log = []

    def build(platform):
        return FakeChannel(platform, log,
                           raise_on_start=platform in raise_start,
                           raise_on_stop=platform in raise_stop)

    return ChannelSwitcher(build), log


def test_first_platform_opens_and_starts_channel():
    sw, log = _switcher()
    ch = sw.for_platform("telegram")
    assert ch.platform == "telegram"
    assert log == [("start", "telegram")]


def test_same_platform_reuses_open_channel_without_restart():
    sw, log = _switcher()
    a = sw.for_platform("telegram")
    b = sw.for_platform("telegram")
    assert a is b
    assert log == [("start", "telegram")]


def test_switching_platform_stops_previous_then_starts_new():
    sw, log = _switcher()
    sw.for_platform("telegram")
    sw.for_platform("linkedin")
    assert log == [("start", "telegram"), ("stop", "telegram"), ("start", "linkedin")]


def test_reopening_same_platform_after_switch_builds_fresh():
    sw, log = _switcher()
    sw.for_platform("telegram")
    sw.for_platform("linkedin")
    sw.for_platform("telegram")
    assert log == [
        ("start", "telegram"), ("stop", "telegram"),
        ("start", "linkedin"), ("stop", "linkedin"),
        ("start", "telegram"),
    ]


def test_close_stops_open_channel_and_is_idempotent():
    sw, log = _switcher()
    sw.for_platform("telegram")
    sw.close()
    sw.close()
    assert log == [("start", "telegram"), ("stop", "telegram")]


def test_close_without_open_channel_is_noop():
    sw, log = _switcher()
    sw.close()
    assert log == []


def test_start_failure_propagates_and_leaves_switcher_empty():
    sw, log = _switcher(raise_start=("linkedin",))
    sw.for_platform("telegram")
    with pytest.raises(RuntimeError, match="cannot start linkedin"):
        sw.for_platform("linkedin")
    assert log == [("start", "telegram"), ("stop", "telegram")]
    sw.for_platform("hh")           # switcher is usable again, no stale state
    assert log[-1] == ("start", "hh")


def test_close_swallows_stop_errors():
    sw, log = _switcher(raise_stop=("telegram",))
    sw.for_platform("telegram")
    sw.close()                      # must not raise even though stop() throws
    sw.for_platform("hh")
    assert ("start", "hh") in log
