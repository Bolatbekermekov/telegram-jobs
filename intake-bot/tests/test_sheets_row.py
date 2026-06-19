from app.domain.lead import ExtractedLead
from app.infrastructure.sheets_repo import lead_to_row


def test_lead_to_row_column_positions():
    lead = ExtractedLead(platform="linkedin", target="linkedin.com/in/x",
                         vacancy_context="Backend", raw_text="raw text")
    row = lead_to_row(lead, row_id=7, now="2026-06-14 10:00")
    assert row == [
        7,                    # id
        "2026-06-14 10:00",   # Дата добавления
        "raw text",           # Исходный текст
        "linkedin",           # Платформа
        "linkedin.com/in/x",  # Источник
        "Backend",            # Вакансия
        "",                   # Сообщение
        "new",                # Статус
        "",                   # Дата отправки
        "",                   # Заметка
    ]
