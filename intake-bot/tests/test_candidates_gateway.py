from app.infrastructure.candidates_gateway import (
    build_vacancy_message, parse_callback, candidate_row_to_lead_row,
    CANDIDATE_COLUMNS,
)


def _row(id="3", platform="linkedin", kind="job",
         url="https://x/1", title="Junior Dev", company="Acme",
         salary="", location="Remote", summary="Python", status="pending",
         date="2026-06-15"):
    return [id, platform, kind, url, title, company, salary, location, summary, status, date]


def test_parse_callback():
    assert parse_callback("approve:3") == ("approve", "3")
    assert parse_callback("skip:12") == ("skip", "12")


def test_build_vacancy_message_text_and_buttons():
    text, buttons = build_vacancy_message(_row())
    assert "LinkedIn" in text and "Junior Dev" in text and "Acme" in text
    assert "Remote" in text
    cbs = {b["callback_data"] for row in buttons for b in row}
    assert cbs == {"approve:3", "skip:3"}


def test_build_vacancy_message_blank_salary_shows_dash():
    text, _ = build_vacancy_message(_row(salary=""))
    assert "—" in text


def test_candidate_row_to_lead_row_maps_main_columns():
    from app.domain.lead import COLUMNS
    row = candidate_row_to_lead_row(_row(), row_id=5, now="2026-06-15 10:00")
    d = dict(zip(COLUMNS, row))
    assert d["id"] == 5
    assert d["Платформа"] == "linkedin"
    assert d["Источник"] == "https://x/1"
    assert "Junior Dev" in d["Вакансия"]
    assert d["Статус"] == "new"
