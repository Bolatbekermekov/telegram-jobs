"""Скрытое обязательное поле даты выхода: заполнять — но очень узко.

Замер живьём 2026-08-26, BlueThrone (Teamtailor), лид #419. Вопрос «Please
enter your available start date*Required» нарисован как `input[type=date]`
внутри блока `hidden max-h-0` (display:none). Блок не раскрывается ни при одном
из четырёх вариантов соседнего вопроса про доступность — проверены все. Форму
это не останавливает: ATS всё равно требует ответ и отклоняет отправку.

Писать в невидимые поля опасно: там живут CSRF-токены и идентификаторы. Поэтому
правило нарочно узкое — только контрол `type=date`, только когда его блок
помечен обязательным И спрашивает именно про НАШУ дату выхода. Дата выпуска,
даты прошлых мест и всё остальное сюда не попадают.
"""
from app.application.hidden_date import wants_availability_date


def test_bluethrone_block():
    assert wants_availability_date(
        "Please enter your available start date*Required") is True


def test_required_marker_is_mandatory():
    # Без пометки обязательности поле отправку не держит, а значит и лезть в
    # невидимый контрол незачем.
    assert wants_availability_date("Please enter your available start date") is False


def test_graduation_date_is_not_ours():
    assert wants_availability_date(
        "When is your graduation date (actual or expected)?*Required") is False


def test_previous_employment_dates_are_not_ours():
    assert wants_availability_date("End date*Required") is False
    assert wants_availability_date("Start date month*Required") is False


def test_blank():
    assert wants_availability_date("") is False
    assert wants_availability_date(None) is False


def test_russian_wording():
    assert wants_availability_date("Дата выхода на работу*Обязательно") is True
