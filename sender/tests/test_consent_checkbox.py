"""The consent checkbox that stops LinkedIn Easy Apply with «Select checkbox to
proceed» — lead #169, measured live on job 4425082337 (2026-07-30).

The screen ("Additional Questions") renders the question as a paragraph and puts
the box under it:

    Enhesa has my consent to collect, store, and process my data for the purpose
    of considering me for employment, and for up to 730 days thereafter.*
    [ ] Yes

Two separate things went wrong there, both in the scraper:

* the box's own label is «Yes» — an ANSWER, not the question — so nothing matched
  the consent rule in map_field, the plan carried no value, and fill_fields'
  `if a.value` skipped it. The question sits in the block that wraps the pair,
  exactly like a radio group's caption, which the scraper already reads that way;
* the snapshot reported `value: "on"` for the UNTICKED box, because that reads the
  HTML value ATTRIBUTE and not the checked state. `_satisfied()` reads that value,
  so every checkbox on every page looked answered and `unmapped_required()` had
  nothing to report — the walk pressed «Проверить» and the form refused.

The DOM says `required=false` / `aria-required="false"` and demands it anyway (the
asterisk lives in the paragraph), so requiredness cannot be leaned on either.

_SCRAPE_JS is JavaScript, so it is tested where it runs — against a page built
from the markup measured live. Local content only, no network.
"""
import pytest

from app.application.auto_apply import FillAction, _satisfied, build_plan
from app.domain.apply_profile import ApplyProfile
from app.domain.page_observation import FieldObs, PageObservation
from app.infrastructure.channels import external_apply as ea

PROFILE = ApplyProfile(full_name="Bolatbek Yermekov", first_name="Bolatbek",
                       last_name="Yermekov", email="a@b.com", city="Astana")

CONSENT_TEXT = ("Enhesa has my consent to collect, store, and process my data for "
                "the purpose of considering me for employment, and for up to 730 "
                "days thereafter.*")

# LinkedIn names every Easy Apply control with a URN, so the `name` carries no
# words a rule could match — the fixture keeps that, otherwise a test would pass
# on a giveaway ("consent" in the name) the real page never provides.
CONSENT_NAME = ("urn:li:fsu_easyApplyFormElement:"
                "(urn:li:jobPosting:4425082337,12345,multipleChoice)")
ALERT_NAME = "jobAlertToggle"

# The measured shape: question in the wrapper, «Yes» on the box itself, plus the
# unrelated job-alert toggle that shares the screen and must stay untouched.
MARKUP = f"""
<div class="modal">
  <h3>Additional Questions</h3>
  <div class="question">
    <p>{CONSENT_TEXT}</p>
    <div class="answer">
      <input type="checkbox" id="consent" name="{CONSENT_NAME}"/>
      <label for="consent">Yes</label>
    </div>
  </div>
  <div class="alert-toggle">
    <input type="checkbox" id="alert" name="{ALERT_NAME}"/>
    <label for="alert">Настройка оповещения</label>
  </div>
</div>
"""


@pytest.fixture(scope="module")
def page():
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch(headless=True)
    except Exception as exc:  # noqa: BLE001 — no browser binary in this environment
        pw.stop()
        pytest.skip(f"chromium unavailable: {exc}")
    pg = browser.new_context().new_page()
    yield pg
    browser.close()
    pw.stop()


def _fields(page, markup):
    page.set_content(markup)
    return {f.name: f for f in ea.scrape_form(page).fields}


# --- what the snapshot says about a checkbox ---------------------------------

def test_an_unticked_checkbox_reports_no_value(page):
    """"on" is the HTML value attribute and says nothing about the state."""
    assert _fields(page, MARKUP)[CONSENT_NAME].value == ""


def test_a_ticked_checkbox_reports_a_value(page):
    ticked = MARKUP.replace('id="consent"', 'id="consent" checked')
    assert _fields(page, ticked)[CONSENT_NAME].value != ""


def test_an_unticked_required_checkbox_reads_as_unanswered():
    """The consequence of the above: `_satisfied` is what `unmapped_required()`
    asks, and with "on" sitting in `value` it answered yes for every checkbox."""
    unticked = FillAction(field=FieldObs(tag="input", type="checkbox", value=""))
    assert _satisfied(unticked) is False


# --- where the question lives ------------------------------------------------

def test_the_question_above_the_box_becomes_its_label(page):
    """«Yes» is the answer; the question is in the block wrapping the pair."""
    assert "consent" in _fields(page, MARKUP)[CONSENT_NAME].label.lower()


def test_the_job_alert_toggle_keeps_its_own_label(page):
    """Widening the lookup must not smear a neighbouring caption over a box that
    already says what it is."""
    assert "оповещения" in _fields(page, MARKUP)[ALERT_NAME].label.lower()


# --- end to end through the real scraper -------------------------------------

def test_the_consent_box_is_planned_to_be_ticked(page):
    page.set_content(MARKUP)
    plan = build_plan(ea.scrape_form(page), PROFILE, "cv.pdf")
    consent = next(a for a in plan.actions if a.field.name == CONSENT_NAME)
    assert consent.value == "true"


def test_the_job_alert_toggle_is_still_left_alone(page):
    page.set_content(MARKUP)
    plan = build_plan(ea.scrape_form(page), PROFILE, "cv.pdf")
    alert = next(a for a in plan.actions if a.field.name == ALERT_NAME)
    assert alert.value == ""


# --- a "No" answer must not tick the box -------------------------------------

class _Loc:
    def __init__(self, page, sel):
        self.page, self.sel = page, sel
        self.first = self

    def count(self):
        return 1

    def nth(self, i):
        return self

    def check(self, timeout=None, force=False):
        self.page.checked.append(self.sel)

    def fill(self, v, **kw):
        pass

    def select_option(self, index=None, **kw):
        pass


class _Page:
    def __init__(self):
        self.checked = []

    def locator(self, sel):
        return _Loc(self, sel)

    def wait_for_timeout(self, ms):
        pass


def _relocation_plan(open_to_relocation):
    f = FieldObs(tag="input", type="checkbox", name="r", ref="3",
                 label="Are you willing to relocate?")
    return build_plan(PageObservation(fields=[f]),
                      ApplyProfile(full_name="B", email="a@b.com",
                                   open_to_relocation=open_to_relocation), "cv.pdf")


def test_a_negative_answer_leaves_the_box_unticked():
    """One checkbox standing in for a yes/no question is answered by TICKING it.
    Planning "No" and then ticking because a non-empty string is truthy answers the
    opposite of what was decided — reachable now that a long wrapper caption can
    reach the yes/no rules above the checkbox branch."""
    plan = _relocation_plan(False)
    assert plan.actions[0].value == "No"        # the decision itself is unchanged
    pg = _Page()
    ea.fill_fields(pg, plan)
    assert pg.checked == []


def test_an_affirmative_answer_still_ticks_the_box(monkeypatch):
    """Галочку ставит виджет `widgets/choice.py`, а не `check(force=True)`:
    прежний способ в HEADED Chrome до спрятанной кнопки не доходил (замер на
    живой форме Recruitee, лид #418). Здесь проверяется решение `fill_fields` —
    что при утвердительном ответе он вообще зовёт виджет; как тот нажимает,
    закреплено в tests/test_choice_widget.py."""
    called = []
    # Имя подмены — `_pick_choice_reason`: с 2026-08-29 `fill_fields` зовёт
    # версию, возвращающую (успех, причина), чтобы отказ называл себя.
    monkeypatch.setattr(ea, "_pick_choice_reason",
                        lambda page, loc, value="", index=None:
                        (called.append(index), (True, ""))[1])
    ea.fill_fields(_Page(), _relocation_plan(True))
    assert called == [0]
