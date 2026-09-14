"""Indeed Apply: отклик на самом Indeed (smartapply.indeed.com) проходит до конца.

Решение владельца 2026-09-14: «По Indeed Apply мы должны полностью
автоматизировать. На риски мне без разницы». До этого такие лиды уходили в
ручные — «форма отклика живёт на самом Indeed» (#1228, #1230, #1236, #1239).

Экраны сняты живьём 2026-09-14 с лида #1230 (Kavant Solutions, AI Engineer):
прошли до «Review your application», ничего не отправив. Контакты из аккаунта →
адрес → резюме → опыт работы («Requested by the employer», есть «Skip») →
проверка → «Submit your application» → post-apply. Страницы ниже повторяют эти
экраны теми же data-testid и той же навигацией по адресам, без вёрстки.
"""
from urllib.parse import parse_qs, urlparse

import pytest

from app.domain.apply_profile import ApplyProfile
from app.domain.channel import ManualApplyRequired, OutreachContent
from app.infrastructure.channels import indeed_smartapply as ia

JOB = "https://www.indeed.com/viewjob?jk=84f280b9c5186dbd"
FORM = "https://smartapply.indeed.com/beta/indeedapply/form/"
PROFILE = ApplyProfile(full_name="Bolatbek Yermekov", first_name="Bolatbek",
                       last_name="Yermekov", email="a@b.com", phone="+7 775 720 0604",
                       city="Astana", country="Kazakhstan")

JOB_PAGE = """<h1>AI Engineer</h1>
<a data-testid="viewjob-indeed-apply" href="@@contact-info-module">Apply now</a>"""

CONTACT = """<h1>Add your contact information</h1>
<label for="fn">First name *</label><input id="fn" name="names-first-name" value="Bolatbek">
<label for="ln">Last name *</label><input id="ln" name="names-last-name" value="Yermekov">
<label for="ph">Phone number</label><input id="ph" type="tel" name="phone" value="775-720-0604">
<button type="button" style="display:none">Continue</button>
<button type="button" onclick="location.href = '@@profile-location?phone='
  + encodeURIComponent(document.getElementById('ph').value)">Continue</button>"""

LOCATION = """<h1>Add your location</h1>
<label for="pc">Postal code</label><input id="pc" name="location-postal-code">
<label for="city">City</label><input id="city" name="location-locality">
<button type="button" onclick="location.href = '@@resume-selection-module/resume-selection?city='
  + encodeURIComponent(document.getElementById('city').value)">Continue</button>"""

RESUME = """<h1>Add a resume</h1>
<fieldset data-testid="resume-selection-radio-card-group" role="radiogroup">
  <div data-testid="resume-selection-file-resume-radio-card" data-checked="true">
    <input data-testid="resume-selection-file-resume-radio-card-input" type="radio"
           value="file" checked name="resume-selection">
    <label data-testid="resume-selection-file-resume-radio-card-label"><span
      id="rn">Bolatbek_Yermekov_Fullstack.pdf</span></label>
    <input data-testid="resume-selection-file-resume-radio-card-file-input" type="file"
           accept="application/pdf" style="display:none"
           onchange="const n = this.files[0].name;
                     setTimeout(() => { document.getElementById('rn').textContent = n; }, 300)">
  </div>
</fieldset>
<button data-testid="continue-button" type="button"
  onclick="location.href = '@@resume-module/profile-work-experience/create?resume='
    + encodeURIComponent(document.getElementById('rn').textContent)">Continue</button>"""

EXPERIENCE = """<h1>Add work experience</h1>
<label for="t">Job title *</label><input id="t" name="work-experience-title" required>
<div role="alert" id="err"></div>
<button data-testid="work-experience-page-create-save-button" type="button"
  onclick="document.getElementById('err').textContent = 'Add a job title to continue.'">
  Save and continue</button>
<button data-testid="work-experience-page-create-skip-button" type="button"
  onclick="location.href = '@@questions-module/question/1'">Skip</button>"""

QUESTION = """<h1>Answer these questions from the employer</h1>
<fieldset><legend>Do you have hands-on experience with LangGraph? *</legend>
  <label><input type="radio" name="q1" value="Yes" required> Yes</label>
  <label><input type="radio" name="q1" value="No" required> No</label>
</fieldset>
<div role="alert" id="err"></div>
<button type="button" onclick="const c = document.querySelector('input[name=q1]:checked');
  if (c) { location.href = '@@review-module?answer=' + c.value; }
  else { document.getElementById('err').textContent = 'Answer this question'; }">Continue</button>"""

REVIEW = """<h1>Review your application</h1>
<button data-testid="submit-application-button" type="button"
  onclick="location.href = '@@post-apply'">Submit your application</button>"""

CONTACT_PATH = "/beta/indeedapply/form/contact-info-module"
RESUME_PATH = "/beta/indeedapply/form/resume-selection-module/resume-selection"
SCREENS = {
    "/viewjob": JOB_PAGE,
    CONTACT_PATH: CONTACT,
    "/beta/indeedapply/form/profile-location": LOCATION,
    RESUME_PATH: RESUME,
    "/beta/indeedapply/form/resume-module/profile-work-experience/create": EXPERIENCE,
    "/beta/indeedapply/form/questions-module/question/1": QUESTION,
    "/beta/indeedapply/form/review-module": REVIEW,
    "/beta/indeedapply/form/post-apply": "<h1>Your application has been submitted!</h1>",
}


def _yes(questions, vacancy_context):
    return {q["id"]: {"choice": 0} for q in questions}


@pytest.fixture(scope="module")
def browser():
    pw = pytest.importorskip("patchright.sync_api")
    try:
        p = pw.sync_playwright().start()
        chrome = p.chromium.launch(headless=True, channel="chrome")
    except Exception as exc:  # noqa: BLE001 — без Chrome тест не запускается
        pytest.skip(f"нет браузера: {type(exc).__name__}")
    yield chrome
    chrome.close()
    p.stop()


@pytest.fixture
def site(browser, monkeypatch):
    """Страница с «сайтом Indeed» за route: (page, экраны, посещённые адреса)."""
    monkeypatch.setattr(ia, "_STEP_WAIT_MS", 3000)
    monkeypatch.setattr(ia, "_RESUME_WAIT_MS", 3000)
    context = browser.new_context()
    page = context.new_page()
    screens = dict(SCREENS)
    visited = []

    def serve(route):
        url = route.request.url
        body = screens.get(urlparse(url).path)
        if body is None:
            route.fulfill(status=204, body="")
            return
        visited.append(url)
        route.fulfill(status=200, content_type="text/html; charset=utf-8",
                      body="<!doctype html><html><body>" + body.replace("@@", FORM)
                           + "</body></html>")

    for host in ("https://www.indeed.com/**", "https://smartapply.indeed.com/**",
                 "https://www.recaptcha.net/**"):
        page.route(host, serve)
    yield page, screens, visited
    context.close()


@pytest.fixture
def ai_cv(tmp_path):
    path = tmp_path / "Bolatbek_Yermekov_AI_Engineer.pdf"
    path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    return str(path)


def _query(visited, tail):
    for url in visited:
        if urlparse(url).path.endswith(tail):
            return parse_qs(urlparse(url).query)
    raise AssertionError(f"экрана {tail} не было: {visited}")


def _apply(page, cv, **kw):
    page.goto(JOB)
    ia.indeed_apply_via_page(page, JOB, OutreachContent(body="letter"), profile=PROFILE,
                             cv_path=cv, answerer=_yes, **kw)


def test_the_application_goes_all_the_way_to_the_confirmation(site, ai_cv):
    page, _, visited = site

    _apply(page, ai_cv)

    assert urlparse(visited[-1]).path.endswith("/post-apply")
    # Телефон из аккаунта Indeed не перезаписан строкой анкеты: у него рядом свой
    # выбор страны, и «+7 775 720 0604» туда не годится.
    assert _query(visited, "/profile-location")["phone"] == ["775-720-0604"]
    assert _query(visited, "/resume-selection")["city"] == ["Astana"]
    # Резюме той роли, под которую отклик, а не загруженное когда-то Fullstack.
    assert _query(visited, "/create")["resume"] == ["Bolatbek_Yermekov_AI_Engineer.pdf"]
    assert _query(visited, "/review-module")["answer"] == ["Yes"]


def test_dry_run_stops_on_the_review_screen(site, ai_cv):
    page, _, visited = site

    with pytest.raises(ManualApplyRequired, match="DRY_RUN"):
        _apply(page, ai_cv, dry_run=True)

    assert not any(urlparse(u).path.endswith("/post-apply") for u in visited)


def test_a_refused_screen_is_named_in_the_forms_own_words(site, ai_cv):
    page, screens, _ = site
    screens[CONTACT_PATH] = """<h1>Add your contact information</h1>
<div role="alert" id="err"></div>
<button type="button" onclick="document.getElementById('err').textContent =
  'Enter a valid phone number'">Continue</button>"""

    with pytest.raises(ManualApplyRequired,
                       match=r"contact-info-module.*Enter a valid phone number"):
        _apply(page, ai_cv)


def test_a_resume_that_does_not_take_stops_the_application(site, ai_cv):
    page, screens, visited = site
    screens[RESUME_PATH] = RESUME.replace(
        "document.getElementById('rn').textContent = n;", "")

    with pytest.raises(ManualApplyRequired, match="AI_Engineer"):
        _apply(page, ai_cv)

    assert not any("/profile-work-experience" in u for u in visited)


def test_a_visible_captcha_goes_to_the_human(site, ai_cv):
    page, screens, visited = site
    screens[CONTACT_PATH] = CONTACT + (
        '<iframe src="https://www.recaptcha.net/recaptcha/enterprise/bframe?k=x"'
        ' style="width:400px;height:500px"></iframe>')

    with pytest.raises(ManualApplyRequired, match="капч"):
        _apply(page, ai_cv)

    assert not any(urlparse(u).path.endswith("/profile-location") for u in visited)
