"""Текущая зарплата: оценка по рынку страны вакансии, а не пустое поле.

Решение владельца 2026-09-13: если текущей зарплаты нет в анкете, называть
среднюю по рынку страны вакансии для уровня Strong Middle (вакансия в России —
по России и так далее), а если страна не видна — по Казахстану. До этого поле
«Current CTC» оставалось пустым (лид #997), и обязательное поле уводило отклик в
ручной.
"""
from app.application.auto_apply import map_field
from app.domain.apply_profile import ApplyProfile
from app.domain.page_observation import FieldObs
from app.infrastructure.openai_client import _QUESTIONS_SYSTEM


def _field(label):
    return FieldObs(tag="input", type="text", label=label, required=True, ref="0")


def test_a_current_salary_without_a_profile_figure_goes_to_the_model():
    action = map_field(_field("What is your current salary?"), ApplyProfile(full_name="B Y"), "cv.pdf")
    assert action.needs_ai and action.source == "ai"


def test_current_ctc_goes_to_the_model_too():
    action = map_field(_field("Current CTC (in LPA)*"), ApplyProfile(full_name="B Y"), "cv.pdf")
    assert action.needs_ai and action.source == "ai"


def test_a_figure_the_owner_wrote_still_wins():
    action = map_field(_field("What is your current salary?"),
                       ApplyProfile(full_name="B Y", current_salary="900000 KZT"), "cv.pdf")
    assert action.value == "900000 KZT" and action.source == "profile"


def test_the_model_is_told_how_to_estimate_it():
    low = _QUESTIONS_SYSTEM.lower()
    assert "текущую зарплату" in low
    assert "strong middle" in low
    assert "казахстан" in low


def test_expectations_are_not_below_the_current_salary():
    assert "не ниже текущей" in _QUESTIONS_SYSTEM.lower()
