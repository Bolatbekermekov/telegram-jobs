"""Forms that arrive partly answered, and dropdowns that can't be typed into.

Every vector here is copied from LinkedIn's Easy Apply step 1, measured live on
2026-07-29 for two real jobs (4431682066, 4434515311) — the same two leads that
had been parking as `manual` run after run.
"""
from app.application.auto_apply import build_plan, map_field
from app.domain.apply_profile import ApplyProfile
from app.domain.page_observation import FieldObs, PageObservation

PROFILE = ApplyProfile(
    full_name="Bolatbek Yermekov", first_name="Bolatbek", last_name="Yermekov",
    email="ermekbolatbek21@gmail.com", phone="+7 775 720 0604",
)

# --- verbatim from the live page ------------------------------------------

EMAIL_SELECT = FieldObs(
    tag="select", type="select-one", label="Email addressEmail address",
    required=True, options=["Select an option", "yermekovbolatbek@gmail.com"],
    value="yermekovbolatbek@gmail.com", ref="0")
COUNTRY_CODE_SELECT = FieldObs(
    tag="select", type="select-one", label="Phone country codePhone country code",
    required=True, options=["Select an option", "Kazakhstan (+7)", "Albania (+355)"],
    value="Kazakhstan (+7)", ref="1")
PHONE_INPUT = FieldObs(tag="input", type="text", label="Mobile phone number",
                       required=True, value="", ref="2")


def _plan(*fields):
    return build_plan(PageObservation(url="https://www.linkedin.com/jobs/view/1/apply/",
                                      fields=list(fields)), PROFILE, "cv.pdf")


def test_the_real_first_step_is_fully_satisfiable():
    """This exact screen was reported as «не смог заполнить обязательное поле»."""
    assert _plan(EMAIL_SELECT, COUNTRY_CODE_SELECT, PHONE_INPUT).unmapped_required() == []


def test_a_prefilled_select_counts_as_answered_even_when_it_differs_from_the_profile():
    """The LinkedIn account email is not the profile email, and that is fine —
    the account is what the employer will see, and it is already chosen."""
    assert _plan(EMAIL_SELECT).unmapped_required() == []


def test_an_untouched_dropdown_does_not_count_as_answered():
    blank = FieldObs(tag="select", type="select-one", label="Country", required=True,
                     options=["Select an option", "Kazakhstan"],
                     value="Select an option", ref="0")
    assert _plan(blank).unmapped_required() == ["Country"]


def test_russian_placeholder_options_are_recognised_too():
    for placeholder in ("Выберите вариант", "Не выбрано", "—", "Choose"):
        blank = FieldObs(tag="select", type="select-one", label="Город", required=True,
                         options=[placeholder, "Астана"], value=placeholder, ref="0")
        assert _plan(blank).unmapped_required() == ["Город"], placeholder


def test_a_dropdown_is_answered_by_option_index_never_by_typing():
    """.fill() on a <select> raises, and on a required field that raise is a
    manual apply — which is exactly how these leads kept dying."""
    field = FieldObs(tag="select", type="select-one", label="Email", required=True,
                     options=["Select an option", "ermekbolatbek21@gmail.com"],
                     value="Select an option", ref="0")
    action = map_field(field, PROFILE, "cv.pdf")
    assert action.choice_index == 1
    assert action.value == "ermekbolatbek21@gmail.com"


def test_a_dropdown_with_no_matching_option_is_left_for_a_human():
    field = FieldObs(tag="select", type="select-one", label="Email", required=True,
                     options=["Select an option", "someone.else@corp.com"],
                     value="Select an option", ref="0")
    assert map_field(field, PROFILE, "cv.pdf").source == "unmapped"


# --- the country code is asked for separately ------------------------------

def test_the_country_code_is_not_typed_twice_into_the_number():
    plan = _plan(COUNTRY_CODE_SELECT, PHONE_INPUT)
    phone = next(a for a in plan.actions if a.field.label == "Mobile phone number")
    assert phone.value == "775 720 0604"


def test_a_lone_phone_field_keeps_the_full_number():
    """No separate country-code control means the number must carry its code."""
    plan = _plan(PHONE_INPUT)
    phone = next(a for a in plan.actions if a.field.label == "Mobile phone number")
    assert phone.value == "+7 775 720 0604"


def test_an_optional_unknown_dropdown_is_never_touched():
    """The one that actually happened: LinkedIn renders its interface-language
    picker inside the contact step. «unknown select -> let the AI pick» answered
    it, the model took the first option, and the whole account switched to Arabic
    — after which no text-based selector matched and the flow was undrivable."""
    language = FieldObs(
        tag="select", type="select-one", label="Выберите язык", required=False,
        options=["العربية (арабский)", "বাংলা (бенгали)", "Русский (Russian)"],
        value="Русский (Russian)", ref="3")
    action = map_field(language, PROFILE, "cv.pdf")

    assert action.needs_ai is False
    assert action.source == "unmapped"
    assert action.choice_index is None
    assert action.value == ""


def test_a_required_unknown_dropdown_still_goes_to_the_model():
    """Only the optional ones are off limits — a required choice must be answered."""
    field = FieldObs(tag="select", type="select-one", label="Preferred shift",
                     required=True, options=["Select an option", "Day", "Night"],
                     value="Select an option", ref="0")
    assert map_field(field, PROFILE, "cv.pdf").needs_ai is True


def test_the_country_code_select_itself_is_never_stripped():
    plan = _plan(COUNTRY_CODE_SELECT, PHONE_INPUT)
    code = next(a for a in plan.actions if "country code" in a.field.label.lower())
    assert code.value in ("", "Kazakhstan (+7)")


# --- salary depends on the vacancy, not on a stored number -------------------

def test_a_salary_question_goes_to_the_model_when_no_figure_is_set():
    """"Minimum you would accept, in £ per month" has a different right answer for
    a London fintech and a remote contract. The model sees the vacancy; a fixed
    string in the profile does not."""
    field = FieldObs(tag="input", type="text", required=True, ref="0",
                     label="What is the minimum salary that you would accept in "
                           "British £ ONLY and per month")
    action = map_field(field, PROFILE, "cv.pdf")

    assert action.needs_ai is True
    assert action.source == "ai"


def test_a_fixed_desired_salary_still_wins():
    field = FieldObs(tag="input", type="text", label="Salary expectation",
                     required=True, ref="0")
    fixed = ApplyProfile(full_name="B Y", email="a@b.com", desired_salary="4000 USD")
    action = map_field(field, fixed, "cv.pdf")

    assert action.needs_ai is False
    assert action.value == "4000 USD"


def test_a_required_salary_box_is_never_left_blank():
    """Empty + required used to park the whole application as `manual`."""
    field = FieldObs(tag="input", type="text", label="Expected compensation",
                     required=True, ref="0")
    plan = build_plan(PageObservation(fields=[field]), PROFILE, "cv.pdf")
    plan.actions[0].value = "3000 GBP"      # what the answerer would put there

    assert plan.unmapped_required() == []


def test_a_salary_mentioned_in_prose_is_not_mistaken_for_a_caption():
    """The model answers prose anyway — the point is it must not be handed a
    stored number as if it were a salary box."""
    field = FieldObs(tag="textarea", type="", required=False, ref="0",
                     label="Describe a project where you had to justify the salary "
                           "budget of your team to leadership")
    fixed = ApplyProfile(full_name="B Y", email="a@b.com", desired_salary="4000 USD")
    assert map_field(field, fixed, "cv.pdf").value != "4000 USD"


def test_a_uuid_field_name_does_not_switch_off_the_caption_rules():
    """Ashby names every control with a UUID, ~37 characters of noise. Measured on
    the label+name string, that pushed a real question past the caption limit and
    disabled every keyword rule for it — the salary question stayed unanswered
    even though the model was answering it correctly in isolation."""
    field = FieldObs(tag="input", type="text", required=True, ref="0",
                     name="8d640ab2-9852-452b-9798-92d28cba1f77",
                     label="What is the minimum salary that you would accept in "
                           "British £ ONLY and per month")
    action = map_field(field, PROFILE, "cv.pdf")

    assert action.needs_ai is True
    assert action.source == "ai"


def test_a_uuid_name_does_not_resurrect_rules_for_real_prose():
    """The limit still has to bite on an actual long question."""
    field = FieldObs(tag="input", type="text", required=False, ref="0",
                     name="8d640ab2-9852-452b-9798-92d28cba1f77",
                     label="Describe in detail a situation where your team had to "
                           "rebuild a service under a hard deadline and what your "
                           "own contribution to that effort was")
    fixed = ApplyProfile(full_name="B Y", email="a@b.com", desired_salary="4000 USD")
    assert map_field(field, fixed, "cv.pdf").value != "4000 USD"


# --- <input type=number> takes digits, and only digits -----------------------

def test_a_currency_answer_is_salvaged_for_a_number_input():
    """Measured on lead 123: the field is <input type=number>, the model answered
    "£5000", and Playwright refused — "Cannot type text into input[type=number]".
    On a required field that refusal parked the whole application."""
    from app.infrastructure.channels.external_apply import numeric_only

    assert numeric_only("£5000") == "5000"
    assert numeric_only("5,000 GBP per month") == "5000"
    assert numeric_only("около 4 500 £") == "4500"
    assert numeric_only("3500.50") == "3500.50"
    assert numeric_only("2 500,75 EUR") == "2500.75"


def test_an_answer_with_no_number_at_all_yields_nothing():
    from app.infrastructure.channels.external_apply import numeric_only

    assert numeric_only("Negotiable") == ""
    assert numeric_only("") == ""
    assert numeric_only(None) == ""


def test_a_numeric_field_tells_the_model_to_answer_with_digits():
    from app.application.auto_apply import answer_ai_fields

    field = FieldObs(tag="input", type="number", required=True, ref="0",
                     label="Minimum salary per month")
    plan = build_plan(PageObservation(fields=[field]), PROFILE, "cv.pdf")
    plan.actions[0].needs_ai = True
    seen = {}

    def answerer(questions, vacancy_context):
        seen["prompt"] = questions[0]["prompt"]
        return {"0": {"id": "0", "text": "5000"}}

    answer_ai_fields(plan, answerer, "vacancy")
    assert "ТОЛЬКО число" in seen["prompt"]
    assert plan.actions[0].value == "5000"
