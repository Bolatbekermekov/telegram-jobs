"""Срок отработки — в тех единицах, которые называет вопрос.

Живьём 2026-09-05 три написания одного вопроса за один прогон:
«notice period (in weeks)» (4461771754), «notice period in days» (4461119453) и
просто «notice period?». Профиль хранит одну строку — «1 month», — и она уезжала
во все три как есть. Поля числовые: LinkedIn отвечал «Недопустимое значение»,
экран не менялся, и обход упирался в предел шагов, ничего не сказав.
"""
from app.domain.apply_profile import ApplyProfile
from app.domain.availability import notice_period_in
from app.domain.page_observation import FieldObs


def test_a_month_becomes_four_weeks():
    assert notice_period_in("What is your notice period (in weeks)?", "1 month") == "4"


def test_a_month_becomes_thirty_days():
    assert notice_period_in("What is your notice period in days?", "1 month") == "30"


def test_weeks_stay_weeks():
    assert notice_period_in("Notice period (in weeks)", "2 weeks") == "2"


def test_days_become_months_when_that_is_the_question():
    assert notice_period_in("Notice period in months", "60 days") == "2"


def test_immediately_is_zero_not_silence():
    """Ноль — честный ответ, а не отсутствие ответа."""
    assert notice_period_in("Notice period in days?", "immediately") == "0"


def test_a_question_without_a_unit_is_left_to_the_usual_path():
    """«Notice period?» без единицы — не наше дело: пусть уходит строка профиля."""
    assert notice_period_in("What is your notice period?", "1 month") == ""


def test_an_unparsable_period_is_not_invented():
    """Выдуманное число уехало бы работодателю обещанием, которого никто не давал."""
    assert notice_period_in("Notice period in weeks", "по договорённости") == ""
    assert notice_period_in("Notice period in weeks", "") == ""


def test_the_planner_uses_the_converted_number():
    """Сквозная проверка: план кладёт в поле число, а не строку профиля."""
    from app.application.auto_apply import build_plan
    from app.domain.page_observation import PageObservation

    profile = ApplyProfile(full_name="B Y", first_name="B", email="a@b.com",
                           notice_period="1 month")
    field = FieldObs(tag="input", type="text",
                     label="What is your notice period (in weeks)?",
                     required=True, ref="0")
    plan = build_plan(PageObservation(url="https://x", fields=[field]), profile, "")
    [action] = plan.actions
    assert action.value == "4"
    assert action.source == "profile"


def test_the_owners_own_answer_is_converted_too():
    """`custom_answers` содержит «notice period: 1 month», и эта ветка стоит
    РАНЬШЕ перевода. Живьём 2026-09-05: повтор лида #877 уже с правкой снова
    отправил «1 month» в поле «notice period in days» — семь знаков,
    «Недопустимое значение». Перевод в единицы вопроса не отменяет ответ
    владельца, он его выражает."""
    from app.application.auto_apply import build_plan
    from app.domain.page_observation import PageObservation

    profile = ApplyProfile(full_name="B Y", first_name="B", email="a@b.com",
                           notice_period="", custom_answers={"notice period": "1 month"})
    for label, want in (("What is your notice period in days?", "30"),
                        ("What is your notice period (in weeks)?", "4")):
        field = FieldObs(tag="input", type="text", label=label, required=True, ref="0")
        [action] = build_plan(
            PageObservation(url="https://x", fields=[field]), profile, "").actions
        assert (action.value, action.source) == (want, "custom"), label


def test_a_rejected_notice_answer_becomes_days():
    """Живьём 2026-09-13 (лиды #339, #866, #997): LinkedIn Easy Apply, «Notice
    Period?» без единицы — строка профиля «1 month» получила «Invalid input», поле
    числовое. Единица не названа, поэтому число ставится только ПОСЛЕ отказа формы
    и в днях: так срок отработки считают формы индийского рынка, откуда эти
    вакансии (рядом у них «Current CTC»)."""
    from app.application.auto_apply import ApplyPlan, FillAction, renumber_notice_answers

    notice = FillAction(field=FieldObs(tag="input", type="text", label="Notice Period?", ref="0"),
                        value="1 month", source="custom")
    city = FillAction(field=FieldObs(tag="input", type="text", label="City", ref="1"),
                      value="Astana", source="profile")
    numeric = FillAction(field=FieldObs(tag="input", type="text", label="Notice period in days",
                                        ref="2"), value="30", source="profile")

    changed = renumber_notice_answers(ApplyPlan(actions=[notice, city, numeric]))

    assert changed == [notice]
    assert notice.value == "30"
    assert (city.value, numeric.value) == ("Astana", "30")


def test_nothing_to_renumber_says_so():
    from app.application.auto_apply import ApplyPlan, FillAction, renumber_notice_answers

    city = FillAction(field=FieldObs(tag="input", type="text", label="City", ref="1"),
                      value="Astana", source="profile")
    assert renumber_notice_answers(ApplyPlan(actions=[city])) == []


def test_a_custom_answer_without_a_unit_question_is_untouched():
    """Перевод трогает только вопрос про срок отработки с названной единицей.
    Всё остальное в `custom_answers` обязано доехать буква в букву."""
    from app.application.auto_apply import build_plan
    from app.domain.page_observation import PageObservation

    profile = ApplyProfile(full_name="B Y", first_name="B", email="a@b.com",
                           custom_answers={"nationality": "Kazakhstan",
                                           "notice period": "1 month"})
    for label, want in (("Nationality", "Kazakhstan"),
                        ("Notice period", "1 month")):
        field = FieldObs(tag="input", type="text", label=label, required=True, ref="0")
        [action] = build_plan(
            PageObservation(url="https://x", fields=[field]), profile, "").actions
        assert action.value == want, label
