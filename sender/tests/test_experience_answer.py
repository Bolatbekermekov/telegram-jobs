"""Вопрос «сколько лет опыта» обязан получать ответ.

Замер 2026-08-03: map_field возвращал `unmapped` для всех формулировок —
«Years of experience», «How many years of experience do you have with Python?»,
«Опыт работы (лет)». На ОБЯЗАТЕЛЬНОМ поле это означает, что вся заявка уходит
в `manual`: она уже стоила генерации письма и поднятого браузера.

Вопрос встречается и в формах ATS, и в LinkedIn Easy Apply, и часто он
обязательный.
"""
from app.application.auto_apply import map_field
from app.domain.apply_profile import ApplyProfile
from app.domain.page_observation import FieldObs

PROFILE = ApplyProfile(full_name="Bolatbek Yermekov", min_experience_years=3)


def _field(label, type_="text", options=(), required=True):
    return FieldObs(tag="input", type=type_, label=label, name="", required=required,
                    options=list(options), value="", combobox=False, ref="1")


def test_a_plain_years_question_is_answered():
    got = map_field(_field("Years of experience"), PROFILE, "/cv.pdf")
    assert got.value == "3"
    assert got.source == "profile"


def test_a_technology_specific_question_is_answered_too():
    got = map_field(_field("How many years of experience do you have with Python?"),
                    PROFILE, "/cv.pdf")
    assert got.value == "3"


def test_the_russian_phrasing_works():
    assert map_field(_field("Опыт работы (лет)"), PROFILE, "/cv.pdf").value == "3"


def test_a_numeric_box_gets_digits_only():
    """<input type=number> отказывается принимать «3 года» — Playwright просто
    не сможет туда напечатать, и обязательное поле утащит заявку в manual."""
    got = map_field(_field("Years of experience", type_="number"), PROFILE, "/cv.pdf")
    assert got.value == "3"


def test_a_dropdown_gets_the_closest_option_at_or_above_the_floor():
    """Списки обычно предлагают диапазоны. Брать первый попавшийся нельзя:
    «0-1» — это не то, что человек про себя говорит."""
    got = map_field(_field("Years of experience", options=["0-1", "1-3", "3-5", "5+"]),
                    PROFILE, "/cv.pdf")
    assert got.value == "3-5"


def test_a_dropdown_without_a_fitting_option_takes_the_highest():
    got = map_field(_field("Years of experience", options=["0-1", "1-2"]),
                    PROFILE, "/cv.pdf")
    assert got.value == "1-2"


def test_prose_about_experience_still_goes_to_the_model():
    """«Расскажите об опыте работы в распределённых командах» — это не вопрос
    про число лет, и подставлять туда «3» бессмысленно."""
    long_label = ("Describe your experience working in distributed teams and how "
                  "many years you have spent doing it in practice")
    got = map_field(_field(long_label), PROFILE, "/cv.pdf")
    assert got.needs_ai is True


def test_a_zero_floor_leaves_the_question_to_the_model():
    """Настройка выключена — значит решает модель, а не подставленный ноль."""
    got = map_field(_field("Years of experience"),
                    ApplyProfile(min_experience_years=0), "/cv.pdf")
    assert got.value != "0"
