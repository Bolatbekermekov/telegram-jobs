from app.application.send_plan import group_leads_by_platform


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
