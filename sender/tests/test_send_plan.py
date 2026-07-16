from app.application.send_plan import group_leads_by_platform, skip_reason
from app.domain.lead import STATUS_FAILED, STATUS_SKIPPED


class _Lead:
    def __init__(self, lead_id, platform):
        self.lead_id = lead_id
        self.platform = platform


def test_groups_leads_by_platform_in_first_seen_order():
    leads = [
        _Lead(1, "hh"), _Lead(2, "linkedin"), _Lead(3, "telegram"),
        _Lead(4, "linkedin"), _Lead(5, "hh"),
    ]
    groups = group_leads_by_platform(leads)
    # platform order = first appearance; each group keeps its leads in order
    assert [p for p, _ in groups] == ["hh", "linkedin", "telegram"]
    assert [l.lead_id for l in dict(groups)["hh"]] == [1, 5]
    assert [l.lead_id for l in dict(groups)["linkedin"]] == [2, 4]
    assert [l.lead_id for l in dict(groups)["telegram"]] == [3]


def test_empty_leads_give_no_groups():
    assert group_leads_by_platform([]) == []


def test_single_platform_one_group():
    groups = group_leads_by_platform([_Lead(1, "hh"), _Lead(2, "hh")])
    assert len(groups) == 1
    assert groups[0][0] == "hh"
    assert len(groups[0][1]) == 2


_KNOWN_T = {"telegram", "linkedin", "hh"}


def _lead(platform):
    return _Lead(0, platform)   # _Lead is defined at the top of this file


def test_skip_unknown_platform():
    assert skip_reason(_lead("myspace"), _KNOWN_T, {}, 10, set(), set()) == (
        STATUS_SKIPPED, "unknown platform: myspace")


def test_skip_platform_whose_channel_failed():
    assert skip_reason(_lead("linkedin"), _KNOWN_T, {}, 10, set(), {"linkedin"}) == (
        STATUS_FAILED, "channel start failed earlier this run")


def test_skip_rate_limited_platform():
    assert skip_reason(_lead("hh"), _KNOWN_T, {}, 10, {"hh"}, set()) == (
        STATUS_SKIPPED, "rate-limited earlier this run")


def test_skip_when_daily_limit_reached():
    assert skip_reason(_lead("telegram"), _KNOWN_T, {"telegram": 10}, 10, set(), set()) == (
        STATUS_SKIPPED, "daily limit reached")


def test_no_skip_when_healthy_and_under_limit():
    assert skip_reason(_lead("telegram"), _KNOWN_T, {"telegram": 3}, 10, set(), set()) is None


def test_unknown_takes_precedence_over_failed():
    assert skip_reason(_lead("x"), _KNOWN_T, {}, 10, set(), {"x"}) == (
        STATUS_SKIPPED, "unknown platform: x")
