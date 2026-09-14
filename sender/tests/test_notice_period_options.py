"""Срок выхода, заданный СПИСКОМ: вариант выбирается по дням, а не по буквам.

Живьём 2026-09-14 (лид #1216, GeekSoft Consulting, LinkedIn Easy Apply, шаг
6/8): «What is your current notice period?*» — `select` с вариантами
«Immediate Joiner / Less than 30 Days / 30 Days / 45 Days / 60 Days». Строка
анкеты «1 month» буквально ни с чем не совпала, вопрос ушёл модели, ответ в
список не встал, и отклик остановился на «не смог заполнить обязательное поле».
Месяц — это 30 дней, и вариант «30 Days» выбирается из анкеты без модели.

Там же вторая половина: модель, не нашедшая ответа, получает первый вариант
(`fill_plan` зажимает индекс), а первым стоит «Select an option». Выбрать
disabled-заглушку нельзя — заполнение падало, и причина читалась неверно.
"""
from app.application.auto_apply import answer_ai_fields, build_plan, map_field
from app.domain.apply_profile import ApplyProfile
from app.domain.availability import notice_option_index
from app.domain.page_observation import FieldObs, PageObservation

LEAD_1216 = ["Select an option", "Immediate Joiner", "Less than 30 Days", "30 Days",
             "45 Days", "60 Days"]
PROFILE = ApplyProfile(full_name="Bolatbek Yermekov", email="a@b.com", notice_period="1 month")


def test_a_month_is_the_thirty_days_option():
    assert notice_option_index(LEAD_1216, "1 month") == 3


def test_two_weeks_is_less_than_thirty_days():
    assert notice_option_index(LEAD_1216, "2 weeks") == 2


def test_immediately_is_the_immediate_option():
    assert notice_option_index(LEAD_1216, "Immediately") == 1


def test_options_worded_in_months():
    options = ["Select an option", "Immediate", "Less than 1 month", "1 month",
               "More than 1 month"]
    assert notice_option_index(options, "1 month") == 3
    assert notice_option_index(options, "2 months") == 4
    assert notice_option_index(options, "2 weeks") == 2


def test_ranges_and_open_ends():
    options = ["Within 15 days", "16-30 days", "1-2 months", "2+ months"]
    assert notice_option_index(options, "10 days") == 0
    assert notice_option_index(options, "1 month") == 1
    assert notice_option_index(options, "6 weeks") == 2
    assert notice_option_index(options, "3 months") == 3


def test_nothing_readable_gives_nothing():
    assert notice_option_index(["January", "February"], "1 month") is None
    assert notice_option_index(LEAD_1216, "после защиты диплома") is None


def test_the_1216_select_is_answered_from_the_profile():
    f = FieldObs(tag="select", type="select-one", label="What is your current notice period?*",
                 required=True, options=LEAD_1216)
    a = map_field(f, PROFILE, "/cv.pdf")
    assert (a.source, a.choice_index, a.value) == ("profile", 3, "30 Days")


def test_an_education_start_month_is_still_not_a_notice_period():
    months = ["Select...", "January", "February", "March"]
    a = map_field(FieldObs(tag="select", type="select-one", label="Start date month",
                           required=True, options=months), PROFILE, "/cv.pdf")
    assert a.source != "profile"


def test_a_model_pick_of_the_placeholder_is_not_an_answer():
    obs = PageObservation(fields=[FieldObs(
        tag="select", type="select-one", label="Preferred shift", required=True,
        options=["Select an option", "Day", "Night"], ref="0")])
    plan = build_plan(obs, PROFILE, "/cv.pdf")

    answer_ai_fields(plan, lambda questions, context: {"0": {"choice": "no idea"}}, "ctx")

    assert plan.actions[0].choice_index is None
    assert plan.unmapped_required() == ["Preferred shift"]
