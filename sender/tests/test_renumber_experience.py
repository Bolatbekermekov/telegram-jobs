"""Вопрос «да/нет» про опыт на числовом поле LinkedIn — после отказа формы числом.

Живьём 2026-09-25 (вакансия 4469924642, Intellias): «Do you have experiance with
LLM APIs?)» — поле в 20 знаков, по подписи вопрос «да/нет», а LinkedIn ждёт
число лет. Модель ответила «Yes, 4+ years.», форма — «Invalid input», заявка
легла в ручные. Подсказки заранее нет: «Invalid input» появляется только после
отказа. Поэтому так же, как у срока отработки (`renumber_notice_answers`): один
повтор числом и только после отказа формы.
"""
from app.application.auto_apply import FillAction, ApplyPlan, renumber_experience_answers
from app.domain.page_observation import FieldObs

LLM_Q = "Do you have experiance with LLM APIs?)"


def _plan(label, value, max_len=20):
    fld = FieldObs(tag="input", type="text", label=label, required=True, max_len=max_len)
    return ApplyPlan(actions=[FillAction(field=fld, value=value, needs_ai=True)])


def test_yes_with_years_becomes_the_number():
    plan = _plan(LLM_Q, "Yes, 4+ years.")
    changed = renumber_experience_answers(plan)
    assert [a.value for a in changed] == ["4"]


def test_no_becomes_zero():
    plan = _plan(LLM_Q, "No, I haven't used them directly.")
    assert [a.value for a in renumber_experience_answers(plan)] == ["0"]


def test_an_answer_that_is_already_a_number_is_left_alone():
    assert renumber_experience_answers(_plan(LLM_Q, "3")) == []


def test_a_long_free_text_field_is_never_turned_into_a_number():
    """Подробный ответ в большом поле — не жертва чужого отказа на том же экране."""
    plan = _plan("Describe your experience with LLM APIs", "Yes. At Atlanti.ai I…",
                 max_len=0)
    assert renumber_experience_answers(plan) == []


def test_a_question_not_about_experience_is_left_alone():
    assert renumber_experience_answers(_plan("Are you comfortable with hybrid?", "Yes")) == []
