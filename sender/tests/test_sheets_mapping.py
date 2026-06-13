from app.infrastructure.sheets_repo import record_to_lead


def test_maps_platform_and_target():
    rec = {
        "id": "5", "Платформа": "linkedin", "Цель": "https://linkedin.com/in/x",
        "Вакансия": "Backend", "Исходный текст": "raw", "Статус": "new",
    }
    lead = record_to_lead(rec, offset=0)
    assert lead.row == 2
    assert lead.platform == "linkedin"
    assert lead.target == "https://linkedin.com/in/x"


def test_defaults_platform_when_empty():
    rec = {"id": "1", "Платформа": "", "Цель": "@nick", "Статус": "new"}
    lead = record_to_lead(rec, offset=3)
    assert lead.row == 5
    assert lead.platform == "telegram"
    assert lead.target == "@nick"
