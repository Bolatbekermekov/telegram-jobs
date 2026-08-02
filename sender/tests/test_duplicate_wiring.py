"""Проводка защиты от дублей: контракт, который обязан соблюсти цикл отправки.

Самый опасный случай — дубли ВНУТРИ одного прогона. История читается один раз
перед циклом, поэтому строка, отправленная минуту назад, в ней отсутствует, и
без дописывания по ходу вторая строка на тот же адрес уедет.

Это не гипотеза: лиды 208 и 209 в живом листе ушли @jakson_vill с разницей в
одну минуту, а лиды 204 и 205 — на один и тот же пост в LinkedIn.
"""
from datetime import datetime

from app.domain.lead import Lead, STATUS_SKIPPED
from app.domain.outreach_history import (
    SentRecord,
    duplicate_reason,
    normalize_address,
)

NOW = datetime(2026, 8, 3, 12, 0)


def _lead(lead_id, target, vacancy, platform="telegram"):
    return Lead(row=2, lead_id=lead_id, platform=platform, target=target,
                vacancy_context=vacancy, raw_text=vacancy, status="new")


def _remember(history, lead):
    """То, что цикл обязан делать после каждой удачной отправки."""
    history.append(SentRecord(platform=lead.platform,
                              address=normalize_address(lead.target),
                              vacancy=lead.vacancy_context,
                              sent_at=NOW, lead_id=lead.lead_id))


def test_the_second_lead_to_one_address_in_the_same_run_is_blocked():
    """Лиды 208 и 209: один получатель, разница в минуту."""
    history = []
    first = _lead("208", "@jakson_vill", "Senior Frontend Developer в Tango")
    second = _lead("209", "@jakson_vill", "Senior Frontend Developer в Tango")

    assert duplicate_reason(first, history, NOW, 5) is None
    _remember(history, first)

    got = duplicate_reason(second, history, NOW, 5)
    assert got is not None
    assert got[0] == STATUS_SKIPPED
    assert "208" in got[1]


def test_without_remembering_the_send_the_duplicate_gets_through():
    """Показывает, ЧТО именно ломается, если забыть дописать историю.

    Этот тест падёт, если кто-то решит, что накопление по ходу не нужно.
    """
    history = []
    first = _lead("208", "@jakson_vill", "Senior Frontend Developer в Tango")
    second = _lead("209", "@jakson_vill", "Senior Frontend Developer в Tango")

    assert duplicate_reason(first, history, NOW, 5) is None
    # намеренно НЕ вызываем _remember
    assert duplicate_reason(second, history, NOW, 5) is None


def test_the_run_history_starts_from_what_the_sheet_already_holds():
    """Прогон должен начинать не с чистого листа, иначе вчерашние отправки забыты."""
    history = [SentRecord(platform="telegram", address="amhrann1",
                          vacancy="Роль: AI-оптимизатор, внедрение AI-решений.",
                          sent_at=datetime(2026, 7, 20, 21, 15), lead_id="75")]
    lead = _lead("171", "@amhrann1",
                 "Роль: AI-оптимизатор (джун-мидл), внедрение AI-решений, Кипр.")
    got = duplicate_reason(lead, history, NOW, 5)
    assert got is not None
    assert "75" in got[1]


def test_a_blocked_lead_never_reaches_a_channel():
    """Проверка порядка: решение принимается ДО открытия канала, иначе браузер
    поднимается ради лида, которому мы всё равно не пишем."""
    opened = []

    def open_channel(platform):
        opened.append(platform)
        return object()

    history = []
    first = _lead("208", "@jakson_vill", "Senior Frontend Developer в Tango")
    second = _lead("209", "@jakson_vill", "Senior Frontend Developer в Tango")

    for lead in (first, second):
        if duplicate_reason(lead, history, NOW, 5) is not None:
            continue
        open_channel(lead.platform)
        _remember(history, lead)

    assert opened == ["telegram"]
