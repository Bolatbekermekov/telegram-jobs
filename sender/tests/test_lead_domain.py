from app.domain.lead import COLUMNS, Lead


# --- The shared column contract ----------------------------------------------
# This literal is checked into BOTH suites — sender/tests/test_lead_domain.py and
# intake-bot/tests/test_lead.py — with identical data, deliberately duplicated. The
# two apps are separate deploys that never import each other, yet both address the
# same Google Sheet by column index, so the only thing that catches a drift in one
# of the two `app/domain/lead.py` copies is each suite pinning the order itself.
# Change one copy of this list, change the other, in the same commit.
#
# What breaks otherwise is silent. The COL_* constants are derived from COLUMNS by
# position, and SheetsRepo.update_resolved writes a lead's platform, target and
# vacancy text as the single span COL_PLATFORM..COL_VACANCY. If the lists disagree
# by one column that span lands on the wrong cells, and a lead's routing — the
# highest-stakes field in the project — is corrupted with no error anywhere.
# Phase 2 of the Threads feature adds «Тип лида», so the drift is scheduled rather
# than hypothetical.
#
# The literal is the contract. Any assertion derived from COLUMNS itself (a
# membership check, or COLUMNS.index(...) round-tripped) is tautological and stays
# green through exactly the change this exists to catch.
_SHEET_COLUMNS = [
    "id",
    "Дата добавления",
    "Исходный текст",
    "Платформа",
    "Источник",
    "Вакансия",
    "Сообщение",
    "Статус",
    "Дата отправки",
    "Заметка",
]


def test_columns_match_the_shared_sheet_contract():
    assert COLUMNS == _SHEET_COLUMNS, (
        "COLUMNS drifted from the shared sheet contract. Both copies must change "
        "together: sender/app/domain/lead.py and intake-bot/app/domain/lead.py."
    )


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
