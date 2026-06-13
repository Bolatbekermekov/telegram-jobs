from app.domain.lead import ExtractedLead


def test_lead_has_target_and_platform():
    lead = ExtractedLead(platform="email", target="r@x.com",
                         vacancy_context="Backend", raw_text="raw")
    assert lead.platform == "email"
    assert lead.target == "r@x.com"


def test_is_valid_requires_target():
    assert ExtractedLead("telegram", "@nick", "v", "r").is_valid() is True
    assert ExtractedLead("telegram", "  ", "v", "r").is_valid() is False
