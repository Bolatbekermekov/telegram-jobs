"""Зарплатный вопрос: ожидаемую считаем, текущую — не выдумываем.

Живьём 2026-09-05 (вакансии 4461771754, 4463333146, 4463348441). Поля под
зарплату у LinkedIn ЧИСЛОВЫЕ: и фраза «Не готов раскрывать текущую зарплату.»
(37 знаков при пределе 20), и короткое «не указываю» (11 знаков) одинаково
отвергаются «Недопустимым значением», экран не меняется, обход упирается в
предел шагов.

Граница проходит между двумя разными вещами. Ожидаемую зарплату модель СЧИТАЕТ
по тексту вакансии — так и написано в профиле («ПУСТО НАМЕРЕННО… пусть считает
модель»). Текущая — ФАКТ о владельце, которого у модели нет, и число на её
месте было бы выдумкой, ушедшей работодателю.
"""
from app.application.auto_apply import _asks_for_a_number, build_plan
from app.domain.apply_profile import ApplyProfile
from app.domain.page_observation import FieldObs, PageObservation


def f(label, **kw):
    return FieldObs(tag="input", type=kw.pop("type", "text"), label=label, ref="0", **kw)


def test_expected_salary_asks_for_a_number():
    assert _asks_for_a_number(f("What is your expected salary ?"))
    assert _asks_for_a_number(f("What is your ECTC in lakhs per annum?"))
    assert _asks_for_a_number(f("Expected CTC"))
    assert _asks_for_a_number(f("Expected compensation"))


def test_current_salary_never_asks_for_a_number():
    """Число здесь было бы выдумкой о владельце, а не ответом."""
    assert not _asks_for_a_number(f("What is your current salary ?"))
    assert not _asks_for_a_number(f("What is your CCTC in lakhs per annum?"))
    assert not _asks_for_a_number(f("Current CTC"))
    assert not _asks_for_a_number(f("Текущая зарплата"))


def test_current_salary_comes_from_the_profile_when_the_owner_filled_it():
    profile = ApplyProfile(full_name="B Y", first_name="B", email="a@b.com",
                           current_salary="2400000", desired_salary="3000000")
    plan = build_plan(PageObservation(
        url="https://x", fields=[f("What is your current salary ?", required=True)]),
        profile, "")
    [action] = plan.actions
    assert action.value == "2400000"
    assert action.source == "profile"


def test_current_salary_is_not_answered_with_the_expected_one():
    """Общее правило про «salary» подхватило бы ОЖИДАЕМУЮ и уверенно сообщило
    работодателю неверный факт. Текущая обязана идти своим правилом, раньше."""
    profile = ApplyProfile(full_name="B Y", first_name="B", email="a@b.com",
                           current_salary="", desired_salary="3000000")
    plan = build_plan(PageObservation(
        url="https://x", fields=[f("What is your current salary ?", required=True)]),
        profile, "")
    [action] = plan.actions
    assert action.value != "3000000"
    # И не выдумано моделью: пустое поле назовут по имени до всякой отправки.
    assert action.value == ""
    assert "current salary" in " ".join(plan.unmapped_required())


def test_expected_salary_still_uses_the_profile_when_it_is_set():
    profile = ApplyProfile(full_name="B Y", first_name="B", email="a@b.com",
                           desired_salary="3000000")
    plan = build_plan(PageObservation(
        url="https://x", fields=[f("What is your expected salary ?", required=True)]),
        profile, "")
    [action] = plan.actions
    assert action.value == "3000000"
