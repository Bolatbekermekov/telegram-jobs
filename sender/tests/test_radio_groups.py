"""Radio questions: one group, one answer, pressed on the right button.

Screening questions come as radios, and emitted one control at a time they carry
no options — nothing can answer them, and the form comes back "Please make a
selection". Measured live on 2026-07-29, LinkedIn job 4434515311: «Are you
comfortable working in an onsite setting?» was exactly that, and it was the last
thing between the walk and the submit button.
"""
from app.application.auto_apply import build_plan, map_field
from app.domain.apply_profile import ApplyProfile
from app.domain.page_observation import FieldObs, PageObservation
from app.infrastructure.channels import external_apply as ea

PROFILE = ApplyProfile(full_name="Bolatbek Yermekov", email="a@b.com",
                       phone="+7 775 720 0604", open_to_relocation=True)

ONSITE_Q = FieldObs(
    tag="input", type="radio", name="onsite-urn:li:fsu_easyApplyFormElement",
    label="Are you comfortable working in an onsite setting?",
    required=True, options=["Yes", "No"], value="", ref="4")


class _Loc:
    def __init__(self, page, sel, n=1):
        self.page, self.sel, self._n = page, sel, n
        self.first = self

    def count(self):
        return self._n

    def nth(self, i):
        loc = _Loc(self.page, self.sel, self._n)
        loc._idx = i
        return loc

    def check(self, timeout=None, force=False):
        self.page.checked.append((self.sel, getattr(self, "_idx", None), force))

    def fill(self, v, **kw):
        self.page.filled[self.sel] = v

    def set_input_files(self, v, **kw):
        self.page.filled[self.sel] = ("file", v)

    def select_option(self, index=None, **kw):
        self.page.filled[self.sel] = ("choice", index)


class _Page:
    def __init__(self, group_size=2):
        self.checked, self.filled = [], {}
        self._group_size = group_size

    def locator(self, sel):
        n = self._group_size if sel.startswith("input[type=radio]") else 1
        return _Loc(self, sel, n)


def _plan_with(action_choice):
    plan = build_plan(PageObservation(fields=[ONSITE_Q]), PROFILE, "cv.pdf")
    plan.actions[0].choice_index = action_choice
    plan.actions[0].value = ONSITE_Q.options[action_choice]
    return plan


def test_a_required_radio_group_is_sent_to_the_model_as_a_choice():
    action = map_field(ONSITE_Q, PROFILE, "cv.pdf")
    assert action.needs_ai is True
    assert action.field.options == ["Yes", "No"]


def test_an_unanswered_required_group_blocks_the_submit():
    plan = build_plan(PageObservation(fields=[ONSITE_Q]), PROFILE, "cv.pdf")
    assert plan.unmapped_required() == [
        "Are you comfortable working in an onsite setting?"]


def test_an_already_checked_group_counts_as_answered():
    answered = FieldObs(tag="input", type="radio", name="q", label="Onsite?",
                        required=True, options=["Yes", "No"], value="Yes", ref="0")
    assert build_plan(PageObservation(fields=[answered]),
                      PROFILE, "cv.pdf").unmapped_required() == []


def test_the_chosen_button_is_pressed_by_index_within_its_group():
    page = _Page()
    ea.fill_fields(page, _plan_with(1))          # "No"

    (sel, idx, force), = page.checked
    assert sel == 'input[type=radio][name="onsite-urn:li:fsu_easyApplyFormElement"]'
    assert idx == 1
    assert force is True          # the real radio is hidden behind a styled label


def test_the_first_option_is_pressed_when_chosen():
    page = _Page()
    ea.fill_fields(page, _plan_with(0))
    assert page.checked[0][1] == 0


def test_a_group_the_name_selector_cannot_find_falls_back_to_the_ref():
    """A name that doesn't survive as a selector must not lose the answer."""
    page = _Page(group_size=0)
    ea.fill_fields(page, _plan_with(1))

    (sel, _idx, force), = page.checked
    assert sel == '[data-af="4"]'
    assert force is True


def test_a_yes_no_profile_question_still_answers_without_the_model():
    relocate = FieldObs(tag="input", type="radio", name="r",
                        label="Are you willing to relocate?", required=True,
                        options=["Yes", "No"], ref="0")
    action = map_field(relocate, PROFILE, "cv.pdf")
    assert action.needs_ai is False
    assert action.choice_index == 0          # profile says open_to_relocation


# --- checkboxes hidden behind styled labels ---------------------------------

def test_a_consent_checkbox_is_ticked_with_force():
    """«I consent» on LinkedIn is `required=false` in the DOM and demanded anyway.
    Without force the check times out, and on an optional field that exception is
    swallowed — the box stayed empty, the form said "Select checkbox to proceed",
    and the step never advanced (lead 126)."""
    consent = FieldObs(tag="input", type="checkbox", name="c", label="I consent",
                       required=False, ref="7")
    page = _Page()
    plan = build_plan(PageObservation(fields=[consent]), PROFILE, "cv.pdf")
    assert plan.actions[0].value == "true"          # recognised as consent

    ea.fill_fields(page, plan)

    (sel, _idx, force), = page.checked
    assert sel == '[data-af="7"]'
    assert force is True


def test_an_unrelated_checkbox_is_left_alone():
    """Only consent-shaped boxes get ticked; «Настройка оповещения» sits on the
    same screen and is none of our business."""
    other = FieldObs(tag="input", type="checkbox", name="n",
                     label="Настройка оповещения", required=False, ref="8")
    page = _Page()
    ea.fill_fields(page, build_plan(PageObservation(fields=[other]), PROFILE, "cv.pdf"))
    assert page.checked == []


# --- an unflagged radio group is still a question ----------------------------

def test_an_unrequired_radio_group_is_answered_anyway():
    """Ashby marks no radio group required, then refuses the submit for one. A
    group of labelled answers to one prompt is a question whatever the DOM says."""
    q = FieldObs(tag="input", type="radio", name="g", required=False, ref="0",
                 label="What is your level in English",
                 options=["Beginner", "Intermediate", "Fluent/Native"])
    assert map_field(q, PROFILE, "cv.pdf").needs_ai is True


def test_an_optional_select_is_still_left_alone():
    """The language picker was a <select>. Answering optional ones switched the
    whole LinkedIn account to Arabic — that lesson stays."""
    picker = FieldObs(tag="select", type="select-one", label="Выберите язык",
                      required=False, ref="0",
                      options=["العربية", "Русский (Russian)"], value="Русский (Russian)")
    assert map_field(picker, PROFILE, "cv.pdf").needs_ai is False


def test_a_personal_status_group_is_answered_prefer_not_to_say():
    """«Marital Status» is the same kind of question as gender, and the form
    carries "I prefer not to say" for exactly this reason."""
    q = FieldObs(tag="input", type="radio", name="m", required=False, ref="0",
                 label="Marital Status",
                 options=["Single", "Married", "I prefer not to say", "Married with kids"])
    action = map_field(q, PROFILE, "cv.pdf")

    assert action.source == "eeo"
    assert action.value == "I prefer not to say"
    assert action.needs_ai is False
