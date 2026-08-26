"""Дата выхода на работу: строка «1 month» не годится там, где нужна ДАТА.

Замер живьём 2026-08-26 на двух формах прогона Remocate:

* Datadog (Greenhouse) — `Start date month*` и `Start date year*` относятся к
  разделу ОБРАЗОВАНИЯ (даты учёбы, рядом `End date year`, «graduation date»).
  Правило по подписи `start date` считало их сроком выхода и вписывало туда
  `1 month`; в поле `type=number` это мусор, и форма отклонила отправку с
  «Start date year*».

* BlueThrone (Teamtailor) — вопрос «Please enter your available start date»
  нарисован как `input[type=date]`. Такой контрол принимает только YYYY-MM-DD:
  строка `1 month` в него не встанет ни при каком раскладе.

Отсюда два правила: дату считаем из срока отработки, а даты учёбы и прошлой
работы под срок выхода не подставляем — они не про нас.
"""
from datetime import date

import pytest

from app.domain.availability import availability_iso


def test_immediately_is_today():
    assert availability_iso("Immediately", today=date(2026, 8, 26)) == "2026-08-26"
    assert availability_iso("ASAP", today=date(2026, 8, 26)) == "2026-08-26"
    assert availability_iso("сразу", today=date(2026, 8, 26)) == "2026-08-26"


def test_days():
    assert availability_iso("14 days", today=date(2026, 8, 26)) == "2026-09-09"
    assert availability_iso("30 дней", today=date(2026, 8, 26)) == "2026-09-25"


def test_weeks():
    assert availability_iso("2 weeks", today=date(2026, 8, 26)) == "2026-09-09"
    assert availability_iso("3 недели", today=date(2026, 8, 26)) == "2026-09-16"


def test_months_land_on_the_same_day_next_month():
    # Календарный месяц, а не 30 суток: «выйду через месяц» человек понимает как
    # то же число следующего месяца, и работодатель прочитает так же.
    assert availability_iso("1 month", today=date(2026, 8, 26)) == "2026-09-26"
    assert availability_iso("2 months", today=date(2026, 8, 26)) == "2026-10-26"
    assert availability_iso("1 месяц", today=date(2026, 1, 31)) == "2026-02-28"


def test_unparsed_gives_nothing():
    # Лучше пусто, чем выдуманная дата: пустое поле удержит отправку и уведёт
    # лид в ручной отклик, а неверная дата уйдёт работодателю молча.
    assert availability_iso("после защиты диплома", today=date(2026, 8, 26)) == ""
    assert availability_iso("", today=date(2026, 8, 26)) == ""


# --- сопоставление поля -----------------------------------------------------

from app.application.auto_apply import map_field                    # noqa: E402
from app.domain.apply_profile import ApplyProfile                   # noqa: E402
from app.domain.page_observation import FieldObs                    # noqa: E402


def _profile(notice="1 month"):
    return ApplyProfile(first_name="A", last_name="B", email="a@b.c",
                        notice_period=notice)


def _map(f, profile=None):
    return map_field(f, profile or _profile(), "/cv.pdf")


def test_date_input_about_availability_gets_a_real_date():
    f = FieldObs(tag="input", type="date", label="Please enter your available start date",
                 required=True)
    a = _map(f)
    assert a.source == "profile"
    assert a.value.count("-") == 2 and a.value[:2] == "20"


def test_education_start_date_is_not_the_notice_period():
    # Раздел образования Greenhouse: рядом End date, graduation date.
    for label in ("Start date month", "Start date year", "End date year"):
        a = _map(FieldObs(tag="input", type="number", label=label, required=True))
        assert a.value != "1 month", f"{label}: подставился срок отработки"
        assert a.source != "profile", f"{label}: взято из профиля, хотя это не про нас"


def test_plain_notice_period_question_still_answered():
    # Не сломать то, что работало: обычный вопрос про срок выхода.
    a = _map(FieldObs(tag="input", type="text", label="Notice period", required=True))
    assert (a.source, a.value) == ("profile", "1 month")


def test_availability_text_question_still_answered():
    a = _map(FieldObs(tag="input", type="text", label="Availability", required=True))
    assert (a.source, a.value) == ("profile", "1 month")


def test_graduation_date_is_not_guessed():
    # Дату выпуска мы не знаем — подставлять туда дату выхода нельзя.
    a = _map(FieldObs(tag="input", type="date",
                      label="When is your graduation date?", required=True))
    assert a.source != "profile"
