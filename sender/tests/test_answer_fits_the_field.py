"""Ответ обязан помещаться в поле, а на числовой вопрос быть числом.

Живьём 2026-09-05, вакансия 4461771754 (дамп `easyapply-steps-4461771754`).
Экран скрининговых вопросов не сменялся ШЕСТЬ раз подряд, и в сохранённой
разметке видно почему — под двумя полями стоит «Недопустимое значение»:

    «What is your current salary ?»          ← «Не готов раскрывать текущую
        зарплату.» — 37 знаков при пределе 20
    «What is your notice period (in weeks)?» ← «1 month» там, где ждут число

Ни одного `role=alert` на странице при этом не было: LinkedIn пишет и предел, и
жалобу в подсказку поля. Отказ был молчаливым — экран просто не менялся.
"""
import pytest

from app.application.auto_apply import _ai_prompt, _asks_for_a_number, _fit_answer
from app.domain.page_observation import FieldObs


def f(label, **kw):
    return FieldObs(tag="input", type=kw.pop("type", "text"), label=label, **kw)


# --- какой вопрос числовой ----------------------------------------------------

def test_linkedin_numeric_questions_are_recognised_despite_type_text():
    """У LinkedIn ВСЕ поля `type="text"`, поэтому прежняя проверка по типу не
    срабатывала там никогда — а спрашивают именно число."""
    assert _asks_for_a_number(f("How many years of work experience do you have with JavaScript?"))
    assert _asks_for_a_number(f("What is your notice period (in weeks)?"))
    assert _asks_for_a_number(f("Стоимость часа", type="number"))


def test_only_the_current_salary_stays_out_of_numbers():
    """Граница проходит НЕ между «зарплата» и «не зарплата».

    Сначала я вывел из ответа модели («Не готов раскрывать текущую зарплату.»),
    что владелец зарплату скрывает, и исключил из числовых обе. Профиль говорит
    обратное: `desired_salary` пуст НАМЕРЕННО — «пусть считает модель по самой
    вакансии». Значит ожидаемая обязана быть числом.

    Текущая — другое дело: это факт о владельце, которого у модели нет, и число
    на её месте было бы выдумкой. Подробности — в test_salary_questions.py."""
    assert _asks_for_a_number(f("What is your expected salary ?"))
    assert not _asks_for_a_number(f("What is your current salary ?"))


# --- что уходит модели --------------------------------------------------------

def test_the_prompt_carries_the_limit_the_page_declared():
    said = _ai_prompt(f("What is your current salary ?", max_len=20))
    assert "не длиннее 20" in said


def test_the_prompt_carries_both_constraints_when_both_apply():
    said = _ai_prompt(f("What is your notice period (in weeks)?", max_len=20))
    assert "ТОЛЬКО число" in said and "не длиннее 20" in said


def test_a_field_without_a_declared_limit_says_nothing_extra():
    assert _ai_prompt(f("Tell us about yourself")) == "Tell us about yourself"


# --- сеть безопасности, когда модель всё равно промахнулась -------------------

def test_an_answer_that_fits_is_left_alone():
    assert _fit_answer("300000", f("What is your expected salary ?", max_len=20)) == "300000"
    assert _fit_answer("что угодно", f("Free form")) == "что угодно"


def test_a_numeric_answer_is_reduced_to_its_number():
    """«1 month» на вопрос «(in weeks)» — не догадка: число из ответа и есть то,
    что спрашивали."""
    assert _fit_answer("1 month", f("What is your notice period (in weeks)?", max_len=3)) == "1"


def test_an_overlong_sentence_is_dropped_not_truncated():
    """Обрезанная фраза уехала бы работодателю предложением без конца, и читает
    её человек. Пустое поле честнее — про него скажут по имени."""
    long = "Не готов раскрывать текущую зарплату."
    assert len(long) > 20
    assert _fit_answer(long, f("What is your current salary ?", max_len=20)) is None


def test_the_dropped_answer_leaves_the_action_unfilled():
    """Сквозная проверка: ответ не влез — поле осталось пустым, а не с мусором."""
    from app.application.auto_apply import answer_ai_fields, ApplyPlan, FillAction

    fld = f("What is your current salary ?", max_len=20, required=True)
    fld.ref = "0"
    action = FillAction(field=fld, value="", needs_ai=True)
    plan = ApplyPlan(actions=[action])

    asked = []

    def _answerer(qs, ctx):
        asked.extend(q["prompt"] for q in qs)
        return {"0": {"text": "Не готов раскрывать текущую зарплату."}}

    answer_ai_fields(plan, _answerer, "")

    # Конвейер ДОЕХАЛ до модели — иначе пустое значение ничего не доказывает.
    assert asked and "не длиннее 20" in asked[0]
    assert action.value == ""
    # И поле названо по имени — человеку видно, что именно осталось незаполненным.
    assert "current salary" in " ".join(plan.unmapped_required())


def test_a_fitting_answer_does_reach_the_action():
    """Обратная сторона: сеть безопасности не должна глотать нормальный ответ."""
    from app.application.auto_apply import answer_ai_fields, ApplyPlan, FillAction

    fld = f("What is your notice period (in weeks)?", max_len=20, required=True)
    fld.ref = "0"
    action = FillAction(field=fld, value="", needs_ai=True)
    plan = ApplyPlan(actions=[action])

    answer_ai_fields(plan, lambda qs, ctx: {"0": {"text": "4"}}, "")
    assert action.value == "4"
