"""Дата рождения: одна дата в анкете, а в поле формы — в том виде, который ждёт поле.

Живьём 2026-09-14 (лид #1216, GeekSoft Consulting, LinkedIn Easy Apply, шаг
5/8): обязательное «Date Of Birth *» нарисовано как
`input data-testid="date-picker-input" lang="en-US"` с кнопкой календаря и без
placeholder. Даты рождения в анкете не было, и отклик ушёл в ручной. Владелец
назвал дату: 30 января 2005.

Там же в анкете лежало `age: "22"` — число, записанное 2026-07-29, хотя
владельцу сейчас 21. Возраст теперь считается от даты рождения, а не хранится.
"""
from datetime import date

import pytest

from app.application.auto_apply import build_plan, map_field
from app.domain.apply_profile import ApplyProfile
from app.domain.birth_date import age_on, birth_date_text
from app.domain.page_observation import FieldObs

DOB = "2005-01-30"
PROFILE = ApplyProfile(full_name="Bolatbek Yermekov", first_name="Bolatbek",
                       last_name="Yermekov", email="a@b.com", date_of_birth=DOB)
NO_DOB = ApplyProfile(full_name="Bolatbek Yermekov", email="a@b.com")


def _map(field, profile=PROFILE):
    return map_field(field, profile, "/cv.pdf")


# --- дата в формате поля ------------------------------------------------------

def test_the_placeholder_names_the_order_and_the_separator():
    assert birth_date_text(DOB, placeholder="MM/DD/YYYY") == "01/30/2005"
    assert birth_date_text(DOB, placeholder="dd/mm/yyyy") == "30/01/2005"
    assert birth_date_text(DOB, placeholder="DD.MM.YYYY") == "30.01.2005"
    assert birth_date_text(DOB, placeholder="ДД.ММ.ГГГГ") == "30.01.2005"
    assert birth_date_text(DOB, placeholder="YYYY-MM-DD") == "2005-01-30"


def test_a_date_control_takes_iso():
    assert birth_date_text(DOB, field_type="date") == "2005-01-30"


def test_an_en_us_date_picker_takes_the_month_first():
    # #1216: у поля нет placeholder, формат виден только по lang календаря.
    assert birth_date_text(DOB, lang="en-US", picker=True) == "01/30/2005"


def test_without_any_hint_the_date_is_iso():
    # 30/01 и 01/30 читаются по-разному в разных странах; ISO — нет.
    assert birth_date_text(DOB) == "2005-01-30"


def test_no_usable_date_gives_nothing():
    assert birth_date_text("") == ""
    assert birth_date_text("30 января") == ""


def test_age_is_counted_from_the_birthday():
    assert age_on(DOB, date(2026, 9, 14)) == 21
    assert age_on(DOB, date(2027, 1, 29)) == 21
    assert age_on(DOB, date(2027, 1, 30)) == 22
    assert age_on("", date(2026, 9, 14)) is None


# --- сопоставление полей ------------------------------------------------------

def test_the_linkedin_date_of_birth_field_gets_the_date():
    f = FieldObs(tag="input", type="text", label="Date Of Birth *", required=True,
                 lang="en-US", date_picker=True)
    a = _map(f)
    assert (a.source, a.value) == ("profile", "01/30/2005")


def test_a_date_control_and_a_russian_caption():
    a = _map(FieldObs(tag="input", type="date", label="Date of birth", required=True))
    assert (a.source, a.value) == ("profile", "2005-01-30")
    a = _map(FieldObs(tag="input", type="text", label="Дата рождения",
                      placeholder="ДД.ММ.ГГГГ"))
    assert (a.source, a.value) == ("profile", "30.01.2005")


def test_without_a_date_in_the_profile_nobody_guesses_it():
    # Дату рождения не угадывают, и модель её не знает: пустое поле удержит
    # отправку, а выдуманная дата ушла бы работодателю как факт.
    a = _map(FieldObs(tag="input", type="text", label="Date of birth", required=True), NO_DOB)
    assert (a.source, a.value, a.needs_ai) == ("unmapped", "", False)


def test_a_paragraph_mentioning_the_birth_date_is_not_a_date_field():
    label = ("Please tell us your full name, date of birth, nationality and why you "
             "would like to join our team")
    a = _map(FieldObs(tag="textarea", type="", label=label[:80], question=label,
                      required=True))
    assert a.value != "2005-01-30" and a.needs_ai


def test_an_age_question_is_answered_from_the_date_of_birth():
    expected = str(age_on(DOB, date.today()))
    a = _map(FieldObs(tag="input", type="number", label="How old are you?", required=True))
    assert (a.source, a.value) == ("profile", expected)


def test_an_age_range_picks_the_range_that_holds_the_age():
    options = ["Select an option", "Under 18", "18-24", "25-34", "35-44"]
    a = _map(FieldObs(tag="select", type="select-one", label="Age", required=True,
                      options=options))
    assert (a.source, a.value) == ("profile", "18-24")


def test_are_you_at_least_18_is_a_yes():
    a = _map(FieldObs(tag="input", type="radio", label="Are you at least 18 years of age?",
                      required=True, options=["Yes", "No"]))
    assert (a.source, a.value) == ("profile", "Yes")


def test_a_bare_age_caption_gets_the_counted_age():
    # Раньше отвечала строка «22» из custom_answers, записанная 2026-07-29.
    a = _map(FieldObs(tag="input", type="text", label="Age", required=True))
    assert (a.source, a.value) == ("profile", str(age_on(DOB, date.today())))


# --- анкета из YAML -------------------------------------------------------------

def test_an_unquoted_yaml_date_is_read_as_iso(tmp_path):
    from app.infrastructure.apply_profile_loader import load_apply_profile

    path = tmp_path / "apply_profile.yml"
    path.write_text("full_name: B Y\ndate_of_birth: 2005-01-30\n", encoding="utf-8")

    assert load_apply_profile(str(path)).date_of_birth == "2005-01-30"


# --- живая разметка #1216 -------------------------------------------------------

@pytest.fixture(scope="module")
def page():
    pw = pytest.importorskip("patchright.sync_api")
    try:
        p = pw.sync_playwright().start()
        browser = p.chromium.launch(headless=True, channel="chrome")
    except Exception as exc:  # noqa: BLE001 — без Chrome тест не запускается
        pytest.skip(f"нет браузера: {type(exc).__name__}")
    pg = browser.new_context().new_page()
    yield pg
    browser.close()
    p.stop()


# Снято с шага 5/8 Easy Apply лида #1216, без классов вёрстки.
LINKEDIN_DOB_STEP = """<body><form>
  <label for="«r1l»"><div>Date Of Birth *</div></label>
  <div><div>
    <input required data-testid="date-picker-input" id="«r1l»" lang="en-US" value="">
    <button type="button" data-testid="date-picker-input-calendar-button"
            aria-label="Embedded calendar" aria-expanded="false" aria-haspopup="dialog"></button>
  </div></div>
</form></body>"""


def test_the_scraper_sees_the_picker_and_the_date_is_typed_month_first(page):
    from app.infrastructure.channels import external_apply as ea

    page.set_content(LINKEDIN_DOB_STEP)
    obs = ea.scrape_form(page)
    field = next(f for f in obs.fields if "Date Of Birth" in f.label)
    assert field.date_picker and field.lang == "en-US"

    ea.fill_fields(page, build_plan(obs, PROFILE, "/cv.pdf"))

    assert page.input_value('[data-testid="date-picker-input"]') == "01/30/2005"
