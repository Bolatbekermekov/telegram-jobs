from app.domain.lead import COLUMNS, ExtractedLead


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


def test_lead_has_target_and_platform():
    lead = ExtractedLead(platform="email", target="r@x.com",
                         vacancy_context="Backend", raw_text="raw")
    assert lead.platform == "email"
    assert lead.target == "r@x.com"


def test_is_valid_requires_target():
    assert ExtractedLead("telegram", "@nick", "v", "r").is_valid() is True
    assert ExtractedLead("telegram", "  ", "v", "r").is_valid() is False


# --- «Заметка» несёт ещё и оценку --------------------------------------------
# Новой колонки под оценку нет намеренно: порядок COLUMNS общий с ноутбучной
# половиной, и любая новая колонка — правка в обеих копиях и в живой таблице
# сразу. «Заметка» же у нового лида пустая (её перезаписывает только отправка,
# уже после того, как оценка отработала своё).


def test_an_unscored_lead_keeps_the_plain_note():
    """Оценки может не быть — сбой модели, вышедший бюджет, нечитаемая ссылка.
    Тогда «Заметка» обязана выглядеть ровно как до появления оценки."""
    lead = ExtractedLead(platform="telegram", target="@acme_hr",
                         vacancy_context="Backend", raw_text="raw",
                         note="контакт из LinkedIn-поста: https://x")

    assert lead.sheet_note() == "контакт из LinkedIn-поста: https://x"


def test_the_score_goes_first_in_the_note():
    """Оценка стоит впереди маршрутной заметки, потому что заметка длинная (в
    ней URL), а в таблице видно начало ячейки — и глазами колонку теперь
    просматривают именно ради оценки."""
    lead = ExtractedLead(platform="telegram", target="@acme_hr",
                         vacancy_context="Backend", raw_text="raw",
                         note="контакт из LinkedIn-поста: https://x",
                         score=35, score_reason="Principal, профиль до Middle")

    assert lead.sheet_note() == ("соответствие профилю 35/100: Principal, профиль "
                                 "до Middle | контакт из LinkedIn-поста: https://x")


def test_a_score_without_a_reason_still_shows_the_number():
    lead = ExtractedLead(platform="email", target="hr@acme.io",
                         vacancy_context="Backend", raw_text="raw", score=88)

    assert lead.sheet_note() == "соответствие профилю 88/100"


def test_a_zero_score_is_not_mistaken_for_no_score():
    """0 — это вердикт «совсем мимо», а None — «не оценили». Проверка на
    истинность вместо `is None` схлопнула бы их в одно."""
    lead = ExtractedLead(platform="email", target="hr@acme.io",
                         vacancy_context="Backend", raw_text="raw",
                         score=0, score_reason="не IT")

    assert lead.sheet_note() == "соответствие профилю 0/100: не IT"
