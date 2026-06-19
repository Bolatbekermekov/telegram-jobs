from app.domain.lead import COLUMNS, Lead


def test_columns_include_platform_and_target():
    assert "Платформа" in COLUMNS
    assert "Источник" in COLUMNS


def test_lead_has_platform_and_target():
    lead = Lead(
        row=2, lead_id="1", platform="telegram", target="@nick",
        vacancy_context="Backend", raw_text="raw", status="new",
    )
    assert lead.platform == "telegram"
    assert lead.target == "@nick"
