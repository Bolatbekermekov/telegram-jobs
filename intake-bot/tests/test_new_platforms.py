from app.domain.bot_commands import command_to_search_platform
from app.infrastructure.candidates_gateway import build_vacancy_message

CANDIDATE_COLUMNS = [
    "id", "Платформа", "Тип", "URL", "Title", "Company",
    "Salary", "Location", "Summary", "Статус", "Дата",
]


def _row(platform):
    values = {
        "id": "7", "Платформа": platform, "Тип": "job",
        "URL": "https://example.com/x", "Title": "Junior Dev", "Company": "Acme",
        "Salary": "", "Location": "Remote", "Summary": "80/100: fits",
        "Статус": "pending", "Дата": "2026-06-21 10:00",
    }
    return [values[c] for c in CANDIDATE_COLUMNS]


def test_commands_map_new_platforms():
    assert command_to_search_platform("/search_remoteok") == "remoteok"
    assert command_to_search_platform("/search_remotive") == "remotive"


def test_badges_for_new_platforms():
    remoteok_text, _ = build_vacancy_message(_row("remoteok"))
    remotive_text, _ = build_vacancy_message(_row("remotive"))
    assert "RemoteOK" in remoteok_text
    assert "Remotive" in remotive_text
