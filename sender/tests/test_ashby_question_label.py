"""Подпись поля берётся из заголовка вопроса, когда своей подписи у поля нет.

Живьём 2026-09-13, Ashby (лид #1163, Ankar): обязательное поле даты нарисовано
`input[type=text]` без `label[for]` и без `aria-label` — только плейсхолдер «Pick
date...». Вопрос «When is the earliest you would want to start at Ankar AI?*»
стоит заголовком в том же блоке поля. Скрапер подписал поле плейсхолдером, и ни
правило даты выхода, ни модель не могли понять, о чём спрашивают: отклик встал на
«не заполнены обязательные поля ['Pick date...']».

Для радиокнопок это правило НЕ годится: их подписи — варианты ответа, и заголовок
вопроса превратил бы все варианты в один и тот же текст.
"""
import pytest

from app.infrastructure.channels.external_apply import scrape_form


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


_ASHBY_FORM = """
<form>
  <div class="_fieldEntry_1e3gg_28 ashby-application-form-field-entry" data-field-path="start">
    <label class="_heading_f7cvd_52 _required_f7cvd_91 ashby-application-form-question-title"
           for="start-hidden">When is the earliest you would want to start at Ankar AI?</label>
    <div class="react-datepicker-wrapper">
      <input type="text" placeholder="Pick date..." value="">
    </div>
  </div>
  <div class="ashby-application-form-field-entry" data-field-path="email">
    <label class="ashby-application-form-question-title" for="email">Email</label>
    <input type="email" id="email" name="email" placeholder="hello@example.com...">
  </div>
</form>
"""


def test_a_field_without_its_own_label_takes_the_question_title(page):
    page.set_content(f"<body>{_ASHBY_FORM}</body>")
    labels = [f.label for f in scrape_form(page).fields]
    assert "When is the earliest you would want to start at Ankar AI?" in labels
    assert "Pick date..." not in labels


def test_a_field_with_its_own_label_keeps_it(page):
    page.set_content(f"<body>{_ASHBY_FORM}</body>")
    assert "Email" in [f.label for f in scrape_form(page).fields]
