"""Числовой вопрос получает число — без процента, валюты и слов.

Живьём 2026-09-25, лид #1576 (LinkedIn Easy Apply, вакансия 4471608620):
«What would you rate your English level skills from 0% to 100%? (Written and
Spoken)» — в поле ушло три символа, и LinkedIn ответил «Invalid input», заявка
легла в ручные. «ТОЛЬКО число» было лишь просьбой к модели, а ответ вида «85%»
уезжал в поле как есть: до цифр он чистился, только если не влезал в лимит.

И сам вопрос считался числовым случайно — слово «rate» совпало с правилом
ЗАРПЛАТЫ. Та же шкала без этого слова («evaluate … from 1 to 10») числом не
считалась вовсе.
"""
import pytest

from app.application.auto_apply import _asks_for_a_number, answer_ai_fields, build_plan
from app.domain.apply_profile import ApplyProfile
from app.domain.page_observation import FieldObs, PageObservation

PROF = ApplyProfile(full_name="Test User", first_name="Test", last_name="User",
                    email="t@example.test", phone="+70000000000", country="Kazakhstan")
ENGLISH = "What would you rate your English level skills from 0% to 100%? (Written and Spoken)"


@pytest.mark.parametrize("label", [
    ENGLISH,
    "Please evaluate your English from 1 to 10",
    "On a scale of 1-10, how strong is your Python?",
    "Your English level (0-100)",
    "What percentage of your time was spent on backend work?",
    "Оцените свой английский от 1 до 10",
])
def test_a_scale_or_percentage_question_asks_for_a_number(label):
    assert _asks_for_a_number(FieldObs(tag="input", type="text", label=label))


@pytest.mark.parametrize("label", [
    "Why do you want to work here?",
    "Describe a project you are proud of from 2023 to 2024",
])
def test_an_open_question_is_not_numeric(label):
    assert not _asks_for_a_number(FieldObs(tag="input", type="text", label=label))


@pytest.mark.parametrize("answer, expected", [
    ("85%", "85"),
    ("~85", "85"),
    ("85 percent", "85"),
    ("85", "85"),
    ("7.5", "7.5"),
])
def test_the_answer_to_a_numeric_field_is_the_number_alone(answer, expected):
    obs = PageObservation(fields=[FieldObs(tag="input", type="text", label=ENGLISH,
                                           required=True, max_len=20)])
    plan = build_plan(obs, PROF, "C:/cv.pdf")
    answer_ai_fields(plan, lambda qs, ctx: {q["id"]: {"text": answer} for q in qs}, "JOB")
    assert [a.value for a in plan.ai_fields] == [expected]


def test_a_numeric_answer_without_a_number_is_left_for_a_human():
    """Слова вместо числа — не число: поле остаётся пустым и назовётся человеку,
    а не уедет в форму «Invalid input»."""
    obs = PageObservation(fields=[FieldObs(tag="input", type="text", label=ENGLISH,
                                           required=True)])
    plan = build_plan(obs, PROF, "C:/cv.pdf")
    answer_ai_fields(plan, lambda qs, ctx: {q["id"]: {"text": "Fluent"} for q in qs}, "JOB")
    assert [a.value for a in plan.ai_fields] == [""]
