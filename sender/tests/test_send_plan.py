from app.application.send_plan import skip_reason
from app.domain.lead import STATUS_FAILED, STATUS_SKIPPED

_KNOWN_T = {"telegram", "linkedin", "hh"}


class _Lead:
    def __init__(self, platform):
        self.platform = platform


def test_skip_unknown_platform():
    assert skip_reason(_Lead("myspace"), _KNOWN_T, {}, 10, set()) == (
        STATUS_SKIPPED, "unknown platform: myspace")


def test_skip_platform_whose_channel_failed():
    assert skip_reason(_Lead("linkedin"), _KNOWN_T, {}, 10, {"linkedin"}) == (
        STATUS_FAILED, "channel start failed earlier this run")


def test_skip_when_daily_limit_reached():
    assert skip_reason(_Lead("telegram"), _KNOWN_T, {"telegram": 10}, 10, set()) == (
        STATUS_SKIPPED, "daily limit reached")


def test_no_skip_when_healthy_and_under_limit():
    assert skip_reason(_Lead("telegram"), _KNOWN_T, {"telegram": 3}, 10, set()) is None


def test_unknown_takes_precedence_over_failed():
    assert skip_reason(_Lead("x"), _KNOWN_T, {}, 10, {"x"}) == (
        STATUS_SKIPPED, "unknown platform: x")
