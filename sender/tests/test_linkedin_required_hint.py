"""«This field is required» рядом с группой — отказ экрана, и поле надо назвать.

Живьём 2026-09-14 (лид #1218, Action1 — анкета Workable внутри Easy Apply): у
группы с галочкой согласия `aria-describedby` ведёт на id, которого на странице
нет, а текст ошибки — соседний абзац после `fieldset`. Ни `role=alert`, ни
подсказки поля не было, поэтому обход не видел отказа и четыре раза жал Review
по одному экрану, пока не упёрся в предел шагов и не сказал бесполезное «не
дошёл за 8 шагов». Разметка снята с дампа `easyapply-steps-4464500779`.
"""
import pytest

from app.infrastructure.channels.linkedin import _first_field_error


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


_CONSENT = """
  <p>Personal data consent*</p>
  <fieldset aria-describedby="error-message-r1j">
    <div role="checkbox" tabindex="0" aria-checked="false">
      <input id="r1k" tabindex="-1" type="checkbox"><label for="r1k"></label>
      <p>By applying for this job, I confirm I have read the Privacy Notice and consent
      to the processing of my data as part of this application.</p>
    </div>
  </fieldset>
"""


def test_the_required_hint_after_a_group_is_a_named_refusal(page):
    page.set_content(f"<body>{_CONSENT}<p>This field is required</p></body>")

    said = _first_field_error(page)

    assert "Personal data consent" in said
    assert "This field is required" in said


def test_a_group_without_the_hint_is_not_an_error(page):
    """Пока форма не отказала, абзаца с ошибкой нет — и отказа тоже нет."""
    page.set_content(f"<body>{_CONSENT}<p>Next question: Notice period</p></body>")

    assert _first_field_error(page) == ""
