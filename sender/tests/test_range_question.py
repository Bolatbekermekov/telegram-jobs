"""Вопрос-шкала («оцените себя от 1 до 5») отвечается числом в её границах.

Живьём 2026-09-14 (лид #1237, Alba Cars на Teamtailor, из Indeed): обязательный
вопрос «How well do you rate yourself in Python?» — это `input type=range`
с min=1, max=5, step=1, спрятанный под нарисованную шкалу. Модель на него
отвечала, но без границ шкалы, а заполнение шло через `fill()`, который для
range не работает, — исключение, «не смог заполнить обязательное поле», ручной
отклик. Страница следит за шкалой своим контроллером и без события `input`
считает, что значение не выбрано («You must select a value»).

Разметка — с живой формы (классы убраны); скрипт повторяет контроллер: на
`input` он показывает число и помечает шкалу изменённой.
"""
import pytest

from app.application.auto_apply import _ai_prompt, build_plan
from app.domain.apply_profile import ApplyProfile
from app.domain.page_observation import FieldObs
from app.infrastructure.channels import external_apply as ea

PROFILE = ApplyProfile(full_name="Bolatbek Yermekov", email="a@b.com")

TEAMTAILOR_RANGE = """
<form>
  <div id="id_6931904">
    <label for="candidate_answers_attributes_10_range">How well do you rate yourself in
      Python?<sup data-asterisk="true" aria-hidden="true">*</sup><span>Required</span></label>
    <div data-controller="forms--inputs--range" data-forms--inputs--range-min-value="1"
         data-forms--inputs--range-max-value="5">
      <span data-forms--inputs--range-target="value">1</span>
      <input value="1" min="1" max="5" required="required" type="range"
             name="candidate[answers_attributes][10][range]"
             id="candidate_answers_attributes_10_range" step="1"
             style="position: absolute; width: 1px; height: 100%; overflow: hidden; opacity: 0; top: 0px;">
    </div>
  </div>
</form>
<script>
(() => {
  const range = document.getElementById('candidate_answers_attributes_10_range');
  const shown = document.querySelector('[data-forms--inputs--range-target="value"]');
  range.addEventListener('input', () => {
    shown.textContent = range.value;
    range.closest('[data-controller]').dataset.changed = 'true';
  });
})();
</script>
"""


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


def _range_field(page):
    return next(f for f in ea.scrape_form(page).fields if f.type == "range")


def test_the_scraper_keeps_the_bounds_of_the_scale(page):
    page.set_content(f"<body>{TEAMTAILOR_RANGE}</body>")
    f = _range_field(page)
    assert (f.range_min, f.range_max, f.range_step) == ("1", "5", "1")


def test_the_model_is_told_the_bounds_of_the_scale():
    f = FieldObs(tag="input", type="range", label="How well do you rate yourself in Python?",
                 required=True, range_min="1", range_max="5", range_step="1")
    assert "от 1 до 5" in _ai_prompt(f)


def test_the_answer_is_set_on_the_scale_so_the_page_sees_it(page):
    page.set_content(f"<body>{TEAMTAILOR_RANGE}</body>")
    plan = build_plan(ea.scrape_form(page), PROFILE, "cv.pdf")
    action = next(a for a in plan.actions if a.field.type == "range")
    action.value = "4 — уверенно владею"          # так модель и отвечает

    ea.fill_fields(page, plan)

    assert page.evaluate("() => document.querySelector('input[type=range]').value") == "4"
    assert page.evaluate("""() => document.querySelector('[data-controller]').dataset.changed
                              || ''""") == "true"
