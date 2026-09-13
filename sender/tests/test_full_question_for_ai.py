"""Модель видит вопрос формы целиком, а не первые 80 знаков подписи.

Живьём 2026-09-13, Workable (лид #1164): обязательное поле одним вопросом
спрашивало шесть вещей — «1) LinkedIn URL 2) Current Location 3) Expected salary
in USD per year 4) Preference for remote/hybrid/on-site/no preference 5) Please
confirm your work authorisation 6) Please confirm when you are available to start
a new position (e.g 1 month notice)». Скрапер режет подпись до 80 знаков, и модели
ушло «…4) Prefe»: половины вопроса она не видела вовсе.

Подпись при этом остаётся короткой — по её длине правила форм отличают настоящую
подпись («Email») от абзаца, и менять это незачем. Полный текст едет рядом,
отдельно, и нужен только тем, кто спрашивает модель.
"""
import pytest

from app.application.auto_apply import _ai_prompt
from app.domain.page_observation import FieldObs
from app.infrastructure.channels.external_apply import scrape_form

_QUESTION = ("1) LinkedIn URL 2) Current Location 3) Expected salary in USD per year "
             "4) Preference for remote/hybrid/on-site/no preference 5) Please confirm your "
             "work authorisation 6) Please confirm when you are available to start a new "
             "position (e.g 1 month notice)")


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


# Разметка поля по живой форме Workable: метка-обёртка со звёздочкой и текстом
# вопроса, `aria-labelledby` на текст, ни `label[for]`, ни `aria-label`.
_WORKABLE_FORM = f"""
<form>
  <label><span>*</span><span id="QA_12099664_label">{_QUESTION}</span>
    <textarea name="QA_12099664" aria-labelledby="QA_12099664_label" required></textarea>
  </label>
  <label for="email">*Email</label><input type="email" id="email" name="email" required>
</form>
"""


def test_the_scraper_keeps_the_whole_question(page):
    page.set_content(f"<body>{_WORKABLE_FORM}</body>")
    field = next(f for f in scrape_form(page).fields if f.name == "QA_12099664")
    assert "available to start a new position (e.g 1 month notice)" in field.question
    assert len(field.label) <= 80          # подпись для правил — прежняя


def test_a_short_caption_is_its_own_question(page):
    page.set_content(f"<body>{_WORKABLE_FORM}</body>")
    field = next(f for f in scrape_form(page).fields if f.name == "email")
    assert field.question == field.label == "*Email"


def test_a_paragraph_question_goes_to_the_model_not_to_a_keyword_rule():
    """Живьём 2026-09-13, прогон 3, тот же лид #1164: поле не ушло модели вовсе.
    Обрубок подписи ровно в 80 знаков сошёл за короткую подпись, и правило
    ТЕКУЩЕЙ зарплаты увидело в нём «2) Current Location» и «3) Expected salary» —
    а текущей зарплаты в профиле нет, значит «оставить пустым». Абзац это или
    подпись, решает длина ВОПРОСА, а не обрубка."""
    from app.application.auto_apply import map_field
    from app.domain.apply_profile import ApplyProfile

    cut = "*1) LinkedIn URL 2) Current Location 3) Expected salary in USD per year 4) Prefe"
    field = FieldObs(tag="textarea", type="textarea", name="QA_12099664", required=True,
                     label=cut, question="*" + _QUESTION)
    action = map_field(field, ApplyProfile(full_name="B Y", email="a@b.com"), "cv.pdf")
    assert action.needs_ai and action.source == "ai"


def test_a_short_caption_still_takes_the_profile_answer():
    from app.application.auto_apply import map_field
    from app.domain.apply_profile import ApplyProfile

    field = FieldObs(tag="input", type="text", label="LinkedIn profile", question="LinkedIn profile")
    action = map_field(field, ApplyProfile(linkedin="https://www.linkedin.com/in/b"), "cv.pdf")
    assert action.value == "https://www.linkedin.com/in/b" and action.source == "profile"


def test_the_model_is_asked_the_whole_question():
    cut = ("*1) LinkedIn URL 2) Current Location 3) Expected salary in USD per year "
           "4) Prefe")
    prompt = _ai_prompt(FieldObs(tag="textarea", label=cut, question="*" + _QUESTION))
    assert "available to start a new position" in prompt
