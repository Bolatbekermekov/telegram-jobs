"""Право работать — по стране из вопроса, а не по одному флагу анкеты.

Живьём 2026-09-01, LinkedIn Easy Apply: на «Are you legally authorized to work
in Sweden?*» система ответила «Yes». Это неправда — владелец гражданин
Казахстана и без спонсорства имеет право работать только там, о чём прямо
сказано в его же search_profile.txt.

Причина была в одной строке: правило искало слова «authorized to work» и
отвечало из `needs_visa_sponsorship`, не читая страну вовсе. При
`needs_visa_sponsorship=False` это означало «да, имею право работать» для любой
страны на свете. Сколько таких ответов ушло — установить нечем: ответы на
вопросы форм никуда не пишутся, вопрос попадает в таблицу только когда ответить
НЕ удалось.
"""
from app.application.auto_apply import map_field
from app.domain.apply_profile import ApplyProfile, work_authorized_in
from app.domain.page_observation import FieldObs

KZ = ApplyProfile(full_name="B", email="a@b.com", country="Kazakhstan",
                  needs_visa_sponsorship=False)


def _ask(label, options=("Yes", "No")):
    return FieldObs(tag="input", type="radio", name="q", label=label,
                    required=True, options=list(options), ref="0")


# --- сама проверка страны -----------------------------------------------------

def test_a_foreign_country_is_answered_no():
    assert work_authorized_in("Are you legally authorized to work in Sweden?*", "Kazakhstan") is False
    assert work_authorized_in("Do you have the right to work in the UK?", "Kazakhstan") is False
    assert work_authorized_in(
        "Are you eligible to work in the United States without sponsorship?",
        "Kazakhstan") is False


def test_the_home_country_is_answered_yes():
    assert work_authorized_in("Are you authorized to work in Kazakhstan?", "Kazakhstan") is True


def test_the_russian_phrasing_and_its_cases_are_read_too():
    """Без этого «в КазахстанЕ» читалось как «страна не названа», и мы
    отказывали себе в вакансии на родине."""
    for q in ("Имеете ли вы право работать в Казахстане?",
              "Есть ли у вас разрешение на работу в Казахстане?"):
        assert work_authorized_in(q, "Kazakhstan") is True
    assert work_authorized_in("Есть ли у вас разрешение на работу в Германии?",
                              "Kazakhstan") is False


def test_an_unnamed_country_is_answered_no():
    """Вопрос почти всегда про страну работодателя, а она у нас чужая.
    Ошибаться здесь надо в сторону честного отказа: потерянная вакансия дешевле
    ложного заявления о своём правовом статусе."""
    assert work_authorized_in("Are you legally authorized to work?", "Kazakhstan") is False


def test_country_aliases_are_recognised():
    us = ApplyProfile(country="United States")
    assert work_authorized_in("Are you authorized to work in the USA?", us.country) is True
    assert work_authorized_in("right to work in America", us.country) is True


# --- как это доходит до формы -------------------------------------------------

def test_the_form_gets_no_for_a_foreign_country():
    action = map_field(_ask("Are you legally authorized to work in Sweden?*"), KZ, "cv.pdf")
    assert action.value == "No"
    assert action.choice_index == 1


def test_the_form_gets_yes_at_home():
    action = map_field(_ask("Are you authorized to work in Kazakhstan?"), KZ, "cv.pdf")
    assert action.value == "Yes"
    assert action.choice_index == 0


def test_sponsorship_is_the_other_half_of_the_same_fact():
    """«Нужно ли вам спонсорство для работы в Швеции?» — да, раз права там нет."""
    action = map_field(_ask("Will you require visa sponsorship to work in Sweden?"),
                       KZ, "cv.pdf")
    assert action.value == "Yes"


def test_sponsorship_at_home_is_not_needed():
    action = map_field(_ask("Требуется ли вам разрешение на работу в Казахстане?"),
                       KZ, "cv.pdf")
    assert action.value == "No"


def test_an_unqualified_sponsorship_question_keeps_the_profile_flag():
    """Без названной страны «нужна ли виза?» отвечает анкета, а не догадка."""
    action = map_field(_ask("Do you require visa sponsorship?"), KZ, "cv.pdf")
    assert action.value == "No"          # needs_visa_sponsorship=False


def test_have_a_permit_and_need_a_permit_are_opposite_questions():
    """Слова почти одни, смысл обратный — разводит их только глагол."""
    have = map_field(_ask("Есть ли у вас разрешение на работу в Казахстане?"), KZ, "cv.pdf")
    need = map_field(_ask("Требуется ли вам разрешение на работу в Казахстане?"), KZ, "cv.pdf")

    assert have.value == "Yes"       # право есть
    assert need.value == "No"        # и потому разрешение не требуется
    # Обе строчки — про одно и то же положение дел, и обе для человека хорошие.


def test_the_same_pair_abroad_flips_both_answers():
    have = map_field(_ask("Do you have the right to work in Germany?"), KZ, "cv.pdf")
    need = map_field(_ask("Will you require sponsorship to work in Germany?"), KZ, "cv.pdf")

    assert have.value == "No"
    assert need.value == "Yes"
