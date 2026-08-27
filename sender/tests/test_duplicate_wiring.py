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


# --- запрос на контакт без письма тоже обязан попадать в память прогона -------
#
# Прогон 2026-08-26. Лид #432 ушёл на https://www.linkedin.com/in/fadaee/ голым
# запросом на контакт (персональные приглашения LinkedIn на месяц кончились) и
# встал в `invited`. Это не отправка, поэтому `_record_sent` его не касался — и
# в памяти прогона он не оставил следа. Через ДВАДЦАТЬ МИНУТ в том же прогоне
# подошёл лид #479 с той же ссылкой, и защита от повторов его не остановила.
# Второй запрос не ушёл только потому, что прогон убили руками. В очереди ждёт
# такая же пара: #483 повторяет #474 (https://www.linkedin.com/in/denisnushtaev/).
#
# Из листа приглашение видно и сейчас: `record_to_sent` считает `invited`
# состоявшимся обращением (test_sheets_mapping). Не хватало ровно памяти
# ВНУТРИ прогона — история читается один раз перед циклом.

class _InviteRepo:
    """Столько от репозитория, сколько нужно ветке `invited_plain`."""

    def __init__(self):
        self.invited = []

    def mark_invited(self, lead, note=""):
        self.invited.append((lead, note))


def test_a_bare_connection_request_blocks_the_next_lead_to_the_same_person():
    """Лиды 432 и 479: один профиль, один прогон, двадцать минут между ними."""
    from app.interface.cli import _record_invited

    history = []
    first = _lead("432", "https://www.linkedin.com/in/fadaee/",
                  "Senior Backend Engineer", platform="linkedin")
    second = _lead("479", "https://www.linkedin.com/in/fadaee/",
                   "Senior Backend Engineer", platform="linkedin")

    assert duplicate_reason(first, history, NOW, 5) is None
    _record_invited(_InviteRepo(), first, "linkedin", history,
                    note="персональные приглашения кончились")

    got = duplicate_reason(second, history, NOW, 5)
    assert got is not None
    assert got[0] == STATUS_SKIPPED
    assert "432" in got[1]


def test_a_parked_invite_is_named_in_the_sheet_the_same_way_as_any_duplicate():
    """Одна ситуация — одно слово в листе.

    Заметка идёт из того же `duplicate_reason`, что и обычный дубль
    («⏭ Лид #430: already applied: та же вакансия (лид #314, 2026-08-22)»).
    Отдельная формулировка означала бы, что в листе одно и то же приходится
    искать двумя разными запросами.
    """
    from app.interface.cli import _record_invited

    history = []
    first = _lead("474", "https://www.linkedin.com/in/denisnushtaev/",
                  "Go Backend Developer, финтех", platform="linkedin")
    second = _lead("483", "https://www.linkedin.com/in/denisnushtaev/",
                   "Go Backend Developer, финтех", platform="linkedin")

    _record_invited(_InviteRepo(), first, "linkedin", history)
    _, note = duplicate_reason(second, history, NOW, 5)
    assert note.startswith("already applied: та же вакансия")


def test_the_trailing_slash_does_not_make_it_a_different_person():
    """`.../in/fadaee/` и `.../in/fadaee` — один человек.

    Ссылку на профиль пишут в лист и поиск, и рука, и хвост у неё то есть, то
    нет. Нормализация уже есть (`normalize_address`), и путь приглашения обязан
    ходить через неё, а не складывать адрес как получилось.
    """
    from app.interface.cli import _record_invited

    history = []
    first = _lead("432", "https://www.linkedin.com/in/fadaee/",
                  "Senior Backend Engineer", platform="linkedin")
    second = _lead("479", "https://www.linkedin.com/in/fadaee",
                   "Совсем другая вакансия: продуктовый аналитик",
                   platform="linkedin")

    _record_invited(_InviteRepo(), first, "linkedin", history)
    assert duplicate_reason(second, history, NOW, 5) is not None


def test_the_invite_still_reaches_the_sheet_with_its_note():
    """Память прогона не заменяет строку в листе: без «Даты отправки» цикл
    `invited` закроет приглашение на следующем же прогоне (invite_age.py),
    поэтому пишется именно `mark_invited`, а не `mark_status`."""
    from app.interface.cli import _record_invited

    repo = _InviteRepo()
    lead = _lead("432", "https://www.linkedin.com/in/fadaee/", "Backend",
                 platform="linkedin")
    _record_invited(repo, lead, "linkedin", [], note="лимит приглашений")

    (written, note), = repo.invited
    assert written is lead
    assert note == "лимит приглашений"


def test_a_failed_sheet_write_still_leaves_the_invite_in_the_run_memory():
    """Запрос на контакт уже у человека — для защиты от повтора важно это, а
    не то, приняла ли таблица строку. Тот же порядок, что в `_record_sent`
    после Sheets-502 на лиде #148."""
    from app.interface.cli import _record_invited

    class _BrokenRepo:
        def mark_invited(self, lead, note=""):
            raise RuntimeError("APIError: [-1]: <!DOCTYPE html> 502")

    history = []
    lead = _lead("432", "https://www.linkedin.com/in/fadaee/", "Backend",
                 platform="linkedin")
    try:
        _record_invited(_BrokenRepo(), lead, "linkedin", history)
    except RuntimeError:
        pass

    assert [r.lead_id for r in history] == ["432"]
