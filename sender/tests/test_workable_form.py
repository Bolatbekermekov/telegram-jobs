"""Форма Workable: вопросы-переключатели, поле фото и честный итог отправки.

Живьём 2026-09-13, прогон 4, лид #1164 (MLabs, apply.workable.com). Снимок страницы
после «Submit application» (.apply_debug/unknown-apply-workable-com-1789294602):

* восемь обязательных вопросов YES/NO — `fieldset[role=radiogroup]` с
  `aria-labelledby` на текст вопроса, внутри `div[role=radio]` и настоящий
  `<input type=radio required aria-hidden="true">` с opacity 0. Скрапер отбрасывал
  такие входы по `aria-hidden` и вопросов не видел вовсе: ни один не был отмечен,
  и браузер не пустил отправку (у формы нет `novalidate`);
* резюме уехало и в «Photo»: подпись обоих файловых полей — «SVGs not supported by
  this browser.», а `accept` у фото — только картинки. Сайт ответил «Please use a
  different file.»;
* отчёт сказал «ВОЗМОЖНО, ЗАЯВКА УЖЕ УШЛА, проверь почту», хотя браузер отказал в
  отправке и заявка точно не ушла.
"""
import pytest

from app.application.auto_apply import map_field
from app.domain.apply_profile import ApplyProfile
from app.domain.channel import ManualApplyRequired
from app.domain.page_observation import FieldObs
from app.infrastructure.channels import external_apply as ea

PROF = ApplyProfile(full_name="B Y", email="a@b.com")


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


_TOP_TIER = ("Top-Tier Tech Experience: Proven software engineering experience at a "
             "globally recognized, high-caliber technology organization (e.g., FAANG, "
             "Bloomberg, Stripe, Shopify, Revolut, Datadog, or direct equivalent) is "
             "strictly required.")

# Разметка по снимку живой формы — без стилей и скриптов вендора.
_WORKABLE = f"""
<form data-ui="application-form">
  <div>
    <span id="photo_label">Photo</span>
    <label><span>SVGs not supported by this browser.</span>
      <input data-ui="avatar" type="file" aria-labelledby="photo_label"
             accept=".jpg,.jpeg,.gif,.png,image/jpeg,image/gif,image/png"></label>
  </div>
  <div>
    <span id="resume_label">Resume</span>
    <label><span>SVGs not supported by this browser.</span>
      <input data-ui="resume" type="file" aria-labelledby="resume_label" required
             accept=".pdf,.doc,.docx,.odt,.rtf,application/pdf,application/msword"></label>
  </div>
  <div>
    <span><strong>*</strong></span>
    <span id="q1_label"><strong>{_TOP_TIER}</strong></span>
    <fieldset role="radiogroup" data-ui="QA_12099656" aria-labelledby="q1_label">
      <div data-ui="option" role="radio" aria-checked="false" aria-required="true">
        <label><input aria-required="true" required aria-hidden="true" tabindex="-1"
                      type="radio" name="QA_12099656" value="true" style="opacity:0">
          <span>YES</span></label>
      </div>
      <div data-ui="option" role="radio" aria-checked="false" aria-required="true">
        <label><input aria-required="true" required aria-hidden="true" tabindex="-1"
                      type="radio" name="QA_12099656" value="false" style="opacity:0">
          <span>NO</span></label>
      </div>
    </fieldset>
  </div>
  <button data-ui="apply-button" type="submit">Submit application</button>
</form>
"""


def _fields(page):
    page.set_content(f"<body>{_WORKABLE}</body>")
    return ea.scrape_form(page).fields


def test_a_yes_no_question_behind_aria_radios_is_seen(page):
    q = next((f for f in _fields(page) if f.name == "QA_12099656"), None)
    assert q is not None, "вопрос YES/NO не виден скраперу"
    assert q.options == ["YES", "NO"]
    assert q.required
    assert q.label.startswith("Top-Tier Tech Experience")
    assert "strictly required." in q.question


def test_the_answer_lands_on_the_aria_radio(page):
    from app.infrastructure.widgets.choice import pick_choice
    q = next(f for f in _fields(page) if f.name == "QA_12099656")
    assert pick_choice(page, page.locator(f'[data-af="{q.ref}"]'), index=1)
    assert page.locator("input[name=QA_12099656][value=false]").is_checked()


def test_a_photo_upload_is_not_given_the_cv(page):
    photo = next(f for f in _fields(page) if f.type == "file" and "image/png" in f.accept)
    action = map_field(photo, PROF, "/cv.pdf")
    assert not action.is_file and action.source == "unmapped"


def test_the_resume_upload_still_gets_the_cv(page):
    resume = next(f for f in _fields(page)
                  if f.type == "file" and "application/pdf" in f.accept)
    action = map_field(resume, PROF, "/cv.pdf")
    assert action.is_file and action.value == "/cv.pdf"


def test_a_file_input_that_takes_only_images_gets_no_documents():
    field = FieldObs(tag="input", type="file", label="Upload", accept="image/*")
    assert map_field(field, PROF, "/cv.pdf").source == "unmapped"


def test_a_file_input_without_accept_still_takes_the_cv():
    field = FieldObs(tag="input", type="file", label="Resume")
    assert map_field(field, PROF, "/cv.pdf").is_file


def test_a_form_the_browser_refused_is_reported_as_not_sent(page, monkeypatch):
    """Обязательный вопрос без ответа в форме без `novalidate`: браузер не пускает
    отправку и сам ничего не пишет в DOM — подсказка «Please select one of these
    options» живёт вне страницы. Итог известен: заявка не ушла."""
    monkeypatch.setattr(ea, "_VERIFY_ATTEMPTS", 1)
    monkeypatch.setattr(ea, "_VERIFY_INTERVAL_MS", 1)
    monkeypatch.setattr(ea, "_dump_form_debug", lambda *a, **kw: None)
    page.set_content(f"<body>{_WORKABLE}</body>")
    page.click("button[data-ui=apply-button]")
    with pytest.raises(ManualApplyRequired, match="НЕ ушла") as caught:
        ea._verify_submitted(page, page.url, submit_before=1)
    assert "ВОЗМОЖНО" not in str(caught.value)
