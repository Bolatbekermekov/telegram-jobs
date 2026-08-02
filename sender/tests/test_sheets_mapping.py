from app.infrastructure.sheets_repo import record_to_lead


def test_maps_platform_and_target():
    rec = {
        "id": "5", "Платформа": "linkedin", "Источник": "https://linkedin.com/in/x",
        "Вакансия": "Backend", "Исходный текст": "raw", "Статус": "new",
    }
    lead = record_to_lead(rec, offset=0)
    assert lead.row == 2
    assert lead.platform == "linkedin"
    assert lead.target == "https://linkedin.com/in/x"


def test_defaults_platform_when_empty():
    rec = {"id": "1", "Платформа": "", "Источник": "@nick", "Статус": "new"}
    lead = record_to_lead(rec, offset=3)
    assert lead.row == 5
    assert lead.platform == "telegram"
    assert lead.target == "@nick"


# --- строка листа -> запись в истории отправок ------------------------------

def test_sent_row_becomes_a_history_record():
    from datetime import datetime
    from app.infrastructure.sheets_repo import record_to_sent
    rec = {"id": "75", "Платформа": "telegram", "Источник": "@amhrann1",
           "Вакансия": "Роль: AI-оптимизатор", "Статус": "sent",
           "Дата отправки": "2026-07-20 21:15"}
    got = record_to_sent(rec)
    assert got.platform == "telegram"
    assert got.address == "amhrann1"          # уже нормализован
    assert got.vacancy == "Роль: AI-оптимизатор"
    assert got.sent_at == datetime(2026, 7, 20, 21, 15)
    assert got.lead_id == "75"


def test_invited_row_counts_as_a_completed_outreach():
    """Приглашение в LinkedIn уже ушло человеку — второе писать нельзя."""
    from app.infrastructure.sheets_repo import record_to_sent
    rec = {"id": "141", "Платформа": "linkedin", "Источник": "https://linkedin.com/in/x",
           "Вакансия": "Backend", "Статус": "invited", "Дата отправки": ""}
    got = record_to_sent(rec)
    assert got is not None
    assert got.sent_at is None                # дата не записана — это нормально


def test_rows_that_never_went_out_are_not_history():
    from app.infrastructure.sheets_repo import record_to_sent
    for status in ("new", "failed", "skipped", "manual", ""):
        rec = {"id": "1", "Платформа": "telegram", "Источник": "@x",
               "Вакансия": "V", "Статус": status, "Дата отправки": "2026-07-20 21:15"}
        assert record_to_sent(rec) is None, status


def test_a_single_digit_hour_still_parses():
    """В листе есть «2026-07-17 2:37» — без ведущего нуля."""
    from datetime import datetime
    from app.infrastructure.sheets_repo import record_to_sent
    rec = {"id": "13", "Платформа": "wellfound", "Источник": "u", "Вакансия": "V",
           "Статус": "sent", "Дата отправки": "2026-07-17 2:37"}
    assert record_to_sent(rec).sent_at == datetime(2026, 7, 17, 2, 37)


def test_an_unreadable_date_does_not_lose_the_record():
    """Строка отправлена — значит история, даже если дату не разобрать."""
    from app.infrastructure.sheets_repo import record_to_sent
    rec = {"id": "9", "Платформа": "telegram", "Источник": "@x", "Вакансия": "V",
           "Статус": "sent", "Дата отправки": "вчера вечером"}
    got = record_to_sent(rec)
    assert got is not None and got.sent_at is None
