from app.application.auto_apply import (
    EEO_ANSWER, build_plan, map_field,
)
from app.domain.apply_profile import ApplyProfile
from app.domain.page_observation import FieldObs, PageObservation

PROF = ApplyProfile(
    full_name="Bolatbek Yermekov", first_name="Bolatbek", last_name="Yermekov",
    email="a@b.com", phone="+7 775 720 0604", city="Astana", country="Kazakhstan",
    linkedin="https://linkedin.com/in/x", github="https://github.com/x",
    needs_visa_sponsorship=False, open_to_relocation=True,
    desired_salary="$70,000/year", notice_period="2 weeks",
    custom_answers={"years of experience": "3", "why do you want": ""},
)
CV = "C:/cv.pdf"


def _m(label, tag="input", type="text", **kw):
    return map_field(FieldObs(tag=tag, type=type, label=label, **kw), PROF, CV)


def test_email_phone_name_links_mapped_from_profile():
    assert _m("Email", type="email").value == "a@b.com"
    assert _m("Phone", type="tel").value == "+7 775 720 0604"
    assert _m("First Name").value == "Bolatbek"
    assert _m("LinkedIn URL").value == "https://linkedin.com/in/x"


def test_file_input_gets_cv():
    a = _m("Resume", type="file")
    assert a.is_file and a.value == CV and a.source == "cv"


def test_eeo_field_prefers_not_to_say():
    a = map_field(FieldObs(tag="select", type="select", label="Gender",
                           options=["Male", "Female", "Prefer not to say"]), PROF, CV)
    assert a.choice_index == 2 and a.value == "Prefer not to say"
    a2 = _m("Gender identity")
    assert a2.value == EEO_ANSWER


def test_sponsorship_and_relocation_yes_no():
    spon = map_field(FieldObs(tag="select", type="select",
                              label="Do you require visa sponsorship?",
                              options=["Yes", "No"]), PROF, CV)
    assert spon.choice_index == 1  # No — profile.needs_visa_sponsorship is False
    reloc = map_field(FieldObs(tag="select", type="select", label="Open to relocation?",
                               options=["Yes", "No"]), PROF, CV)
    assert reloc.choice_index == 0  # Yes


def test_custom_answer_match_and_empty_falls_through_to_ai():
    assert _m("Years of experience").value == "3"
    why = _m("Why do you want to work here?", tag="textarea")
    assert why.needs_ai and why.value == ""


def test_free_text_without_profile_match_goes_to_ai():
    a = _m("Describe a challenging project", tag="textarea")
    assert a.needs_ai


def test_readiness_and_unmapped_required():
    obs = PageObservation(fields=[
        FieldObs(tag="input", type="email", label="Email", required=True),
        FieldObs(tag="input", type="text", label="Unknown mandatory code", required=True),
    ])
    plan = build_plan(obs, PROF, CV)
    assert "Unknown mandatory code" in plan.unmapped_required()
    assert plan.ready_to_submit() is False


from app.application.auto_apply import answer_ai_fields


def test_answer_ai_fields_fills_text_and_choice_and_readiness():
    obs = PageObservation(fields=[
        FieldObs(tag="textarea", type="text", label="Why do you want to work here?",
                 required=True),
        FieldObs(tag="select", type="select", label="Preferred team",
                 options=["Backend", "Frontend"], required=True),
    ])
    plan = build_plan(obs, PROF, CV)
    assert plan.ready_to_submit() is False        # AI fields empty pre-answering

    def answerer(questions, vacancy_context):
        assert vacancy_context == "JOB TEXT"
        out = {}
        for q in questions:
            if q["type"] == "text":
                out[q["id"]] = {"text": "Because I build AI agents daily."}
            else:
                out[q["id"]] = {"choice": 0}
        return out

    answer_ai_fields(plan, answerer, "JOB TEXT")
    vals = [a.value for a in plan.actions]
    assert "Because I build AI agents daily." in vals
    assert plan.actions[1].choice_index == 0 and plan.actions[1].value == "Backend"
    assert plan.ready_to_submit() is True


def test_answer_ai_fields_noop_without_answerer():
    obs = PageObservation(fields=[FieldObs(tag="textarea", label="Why", required=False)])
    plan = build_plan(obs, PROF, CV)
    answer_ai_fields(plan, None, "ctx")           # must not raise
    assert plan.ai_fields[0].value == ""


def test_cv_only_attached_to_resume_not_cover_letter_or_portfolio():
    resume = _m("Attach Resume", type="file")
    assert resume.is_file and resume.value == CV
    cover = _m("Attach Cover Letter", type="file")
    assert not cover.is_file and cover.value == "" and cover.source == "unmapped"
    portfolio = _m("Attach Portfolio", type="file")
    assert not portfolio.is_file and portfolio.source == "unmapped"


def test_recognised_field_without_profile_value_stays_empty_not_ai():
    # PROF has no portfolio -> a "Personal website" field must not get AI prose.
    a = _m("Personal website", type="url")
    assert a.needs_ai is False and a.value == "" and a.source == "unmapped"


def test_unknown_plain_input_is_unmapped_not_ai():
    a = _m("Internal reference number")
    assert a.needs_ai is False and a.source == "unmapped"


def test_note_and_why_inputs_still_go_to_ai():
    assert _m("Personal note").needs_ai is True
    assert _m("Why do you want to work here?").needs_ai is True
