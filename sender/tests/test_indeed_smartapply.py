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
    monkeypatch.setattr(ia, "_dump_form_debug", lambda page, tag, locator=None: None)
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


def test_the_resume_step_is_read_after_its_cards_arrive(site, ai_cv):
    """Живьём 2026-09-14 (#1228, #1230): заголовок «Add a resume» приходит раньше
    карточек и поля загрузки — Indeed дорисовывает их запросом. Бот смотрел сразу
    и объявлял «на шаге резюме нет загрузки файла»."""
    page, screens, visited = site
    late = RESUME.replace('<fieldset', '<template id="late"><fieldset').replace(
        '</fieldset>', '</fieldset></template>') + """
<script>
  setTimeout(() => {
    const t = document.getElementById('late');
    t.replaceWith(t.content.cloneNode(true));
  }, 1500);
</script>"""
    screens[RESUME_PATH] = late

    _apply(page, ai_cv)

    assert _query(visited, "/create")["resume"] == ["Bolatbek_Yermekov_AI_Engineer.pdf"]


def test_continue_is_awaited_while_the_upload_is_processed(site, ai_cv):
    """Живьём 2026-09-14 (#1228, прогон 7): резюме встало, а «Continue» ещё
    выключен, пока Indeed разбирает файл, — бот писал «нет кнопки Continue»."""
    page, screens, visited = site
    screens[RESUME_PATH] = RESUME.replace(
        '<button data-testid="continue-button" type="button"',
        '<button data-testid="continue-button" type="button" disabled').replace(
        "setTimeout(() => { document.getElementById('rn').textContent = n; }, 300)",
        "setTimeout(() => { document.getElementById('rn').textContent = n; }, 300); "
        "setTimeout(() => { document.querySelector('[data-testid=continue-button]')"
        ".disabled = false; }, 2000)")

    _apply(page, ai_cv)

    assert _query(visited, "/create")["resume"] == ["Bolatbek_Yermekov_AI_Engineer.pdf"]


EDUCATION = """<h1>Add education</h1>
<label for="lvl">Level of education *</label><input id="lvl" name="education-level" required>
<button data-testid="education-page-create-save-button" type="submit">Save and continue</button>
<button data-testid="education-page-create-skip-button" type="button"
  onclick="location.href = '@@questions-module/question/1'">Skip</button>"""


def test_an_education_section_the_employer_asks_for_is_skipped(site, ai_cv):
    """Живьём 2026-09-14 (#1230, #1239, прогон 8): после опыта работы Indeed
    открыл `resume-module/profile-education/create` — «Level of education *» и
    «Skip». Сначала адрес бывает промежуточным `resume-module`."""
    page, screens, visited = site
    screens["/beta/indeedapply/form/resume-module/profile-work-experience/create"] = \
        EXPERIENCE.replace("@@questions-module/question/1", "@@resume-module")
    screens["/beta/indeedapply/form/resume-module"] = """<h1>AI Engineer</h1>
<script>setTimeout(() => location.replace('@@resume-module/profile-education/create'), 800)</script>"""
    screens["/beta/indeedapply/form/resume-module/profile-education/create"] = EDUCATION

    _apply(page, ai_cv)

    assert urlparse(visited[-1]).path.endswith("/post-apply")
    assert any("/profile-education/create" in u for u in visited)


def test_the_out_of_country_notice_is_continued(site, ai_cv):
    """Живьём 2026-09-14 (#1236, ae.indeed.com, прогон 8): после контактов экран
    `ooc-continue-or-job-search` — «Search jobs near you / Return to job search /
    Continue applying». Это предупреждение, а не вопрос: право работать в ОАЭ
    спросят отдельно, и на него ответят честно."""
    page, screens, visited = site
    screens[CONTACT_PATH] = CONTACT.replace("@@profile-location?phone=",
                                            "@@ooc-continue-or-job-search?phone=")
    screens["/beta/indeedapply/form/ooc-continue-or-job-search"] = """<h1>AI Engineer</h1>
<h2>Search for jobs in Kazakhstan instead</h2>
<button type="button" onclick="location.href = 'https://www.indeed.com/jobs'">Search jobs near you</button>
<button type="button" onclick="location.href = 'https://www.indeed.com/jobs'">Return to job search</button>
<button type="button" onclick="location.href = '@@profile-location?phone=775-720-0604'">Continue applying</button>"""

    _apply(page, ai_cv)

    assert urlparse(visited[-1]).path.endswith("/post-apply")


LAST_WORKING_QUESTION = """<h1>Answer these questions from the employer</h1>
<label for="lw">What is your last working date? *</label>
<input id="lw" type="text" required name="q_2bc9198f4bbc8b206c81bbf86b49f469">
<div role="alert" id="err"></div>
<button type="button" onclick="const v = document.getElementById('lw').value;
  if (/^\\d{2}\\/\\d{2}\\/\\d{4}$/.test(v)) { location.href = '@@review-module?date=' + encodeURIComponent(v); }
  else { document.getElementById('err').textContent = 'Enter a date in mm/dd/yyyy'; }">Continue</button>
<script>window._initialData = JSON.parse("{\\"questions\\":[{\\"labelHtml\\":\\"What is your last working date?\\",\\"type\\":\\"TEXT\\",\\"name\\":\\"q_2bc9198f4bbc8b206c81bbf86b49f469\\",\\"required\\":true,\\"inputDatePattern\\":\\"MM/dd/yyyy\\"}]}");</script>"""


def test_a_date_question_takes_the_pattern_indeed_keeps_in_the_page_data(site, ai_cv):
    """Живьём 2026-09-14 (#1228, прогон 8): «What is your last working date? *» —
    простой `input type=text` без placeholder; формат `MM/dd/yyyy` лежит только в
    данных страницы (`inputDatePattern`). Последний рабочий день — конец срока
    отработки из анкеты."""
    page, screens, visited = site
    screens["/beta/indeedapply/form/questions-module/question/1"] = LAST_WORKING_QUESTION
    profile = ApplyProfile(**{**PROFILE.__dict__, "notice_period": "1 month"})

    page.goto(JOB)
    ia.indeed_apply_via_page(page, JOB, OutreachContent(body="letter"), profile=profile,
                             cv_path=ai_cv, answerer=_yes)

    assert urlparse(visited[-1]).path.endswith("/post-apply")
    (typed,) = _query(visited, "/review-module")["date"]
    assert len(typed) == 10 and typed[2] == "/" and typed[5] == "/"


def test_date_patterns_are_read_from_escaped_page_data():
    html = ('{\\"id\\":\\"16813535008\\",\\"labelHtml\\":\\"What is your last working date?\\",'
            '\\"type\\":\\"TEXT\\",\\"name\\":\\"q_2bc9198f4bbc8b206c81bbf86b49f469\\",'
            '\\"required\\":true,\\"inputDatePattern\\":\\"MM\\/dd\\/yyyy\\",'
            '\\"localizedDatePattern\\":\\"mm\\/dd\\/yyyy\\"}')
    assert ia.date_patterns(html) == {"q_2bc9198f4bbc8b206c81bbf86b49f469": "MM/dd/yyyy"}


def test_the_apply_button_gets_a_real_click(site, ai_cv):
    """Живьём 2026-09-14 (#1236, ae.indeed.com): «Apply with Indeed» не открыл форму
    от нативного el.click() — «кнопка нажата, а форма не открылась»."""
    page, screens, visited = site
    screens["/viewjob"] = """<h1>AI Engineer</h1>
<button id="indeedApplyButton" type="button">Apply with Indeed</button>
<script>
  document.getElementById('indeedApplyButton').addEventListener('click', e => {
    if (e.isTrusted) location.href = '@@contact-info-module';
  });
</script>"""

    _apply(page, ai_cv)

    assert urlparse(visited[-1]).path.endswith("/post-apply")


def test_a_visible_captcha_goes_to_the_human(site, ai_cv):
    page, screens, visited = site
    screens[CONTACT_PATH] = CONTACT + (
        '<iframe src="https://www.recaptcha.net/recaptcha/enterprise/bframe?k=x"'
        ' style="width:400px;height:500px"></iframe>')

    with pytest.raises(ManualApplyRequired, match="капч"):
        _apply(page, ai_cv)

    assert not any(urlparse(u).path.endswith("/profile-location") for u in visited)
