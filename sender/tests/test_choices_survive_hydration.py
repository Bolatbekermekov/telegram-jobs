"""Выбранные варианты переживают подключение React к готовой форме.

Живьём 2026-09-14 (лид #1233, Modus Create на Greenhouse, два прогона подряд):
форма приходит готовым HTML, а React подключается к ней позже — сеть на этой
странице затихла только через 14 с. Всё, что отмечено до подключения, React
сбрасывает из своего пустого состояния. Бот выбирал «What type of employment are
you open to?» сразу после загрузки, к нажатию «Submit» группа снова была пуста,
и отправка не проходила. Отмеченное после подключения держится — и скриптом, и
мышью. Поэтому перед отправкой выбранное подтверждается ещё раз.

Заодно проверка «пустые обязательные поля»: Greenhouse ставит `required` на
КАЖДУЮ галочку группы и не снимает его, когда одна отмечена, — браузер держит
неотмеченные `:invalid`, и заметка называла пустой группу, где ответ был.
"""
import pytest

from app.application.auto_apply import build_plan
from app.domain.apply_profile import ApplyProfile
from app.infrastructure.channels import external_apply as ea

NAME = "question_32480382003[]"
PROFILE = ApplyProfile(full_name="Bolatbek Yermekov", email="a@b.com")


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


def _option(n: str, label: str, checked: bool = False) -> str:
    return f"""
    <div><div><input required type="checkbox" id="q_{n}" name="{NAME}" value="{n}"
      {'checked' if checked else ''}></div><label for="q_{n}">{label}</label></div>"""


def _group(checked_last: bool = False) -> str:
    return f"""
  <fieldset id="{NAME}" aria-required="true">
    <legend>What type of employment are you open to? <span>*</span></legend>
    {_option("7003", "Part-time")}{_option("8003", "Contract")}{_option("9003", "Full time employment", checked_last)}
  </fieldset>"""


def _checked(page) -> list:
    return page.evaluate(
        """(n) => [...document.querySelectorAll('[name="' + n + '"]')]
                    .filter(e => e.checked).map(e => e.value)""", NAME)


def test_a_group_with_one_ticked_box_is_not_reported_empty(page):
    page.set_content(f"""<body><form>
      <input data-af="0" type="text" name="first_name" value="Bolatbek" required>
      {_group(checked_last=True)}
    </form></body>""")
    assert ea._invalid_required(page) == []


def test_a_group_with_nothing_ticked_is_still_reported(page):
    page.set_content(f"""<body><form>
      <input data-af="0" type="text" name="first_name" value="Bolatbek" required>
      {_group()}
    </form></body>""")
    assert ea._invalid_required(page) == [NAME]


# Подключение React моделируется событием в DOM: оно доходит до страницы из
# любого мира исполнения, а сброс делает ровно то, что делал React на живой форме.
_HYDRATING_FORM = f"""<body><form>{_group()}</form>
<script>
(() => {{
  document.addEventListener('hydrate', () => {{
    for (const box of document.querySelectorAll('input[type=checkbox]')) box.checked = false;
  }});
}})();
</script></body>"""


def test_a_choice_reset_after_filling_is_given_again_before_submit(page):
    page.set_content(_HYDRATING_FORM)
    plan = build_plan(ea.scrape_form(page), PROFILE, "cv.pdf")
    action = next(a for a in plan.actions if a.field.name == NAME)
    action.choice_index, action.value = 2, "Full time employment"     # ответ модели
    ea.fill_fields(page, plan)
    assert _checked(page) == ["9003"]

    page.evaluate("() => document.dispatchEvent(new Event('hydrate'))")
    assert _checked(page) == []

    ea._reassert_choices(page, plan)

    assert _checked(page) == ["9003"]


def test_choices_are_reasserted_before_the_submit_click(monkeypatch):
    from tests.test_external_apply import FakePage
    from app.domain.page_observation import PageObservation

    page = FakePage(PageObservation(url="https://job-boards.greenhouse.io/x"),
                    present={ea.SEL_SUBMIT})
    monkeypatch.setattr(ea, "fill_fields", lambda page, plan, **kw: None)
    monkeypatch.setattr(ea, "_reassert_choices",
                        lambda page, plan: page.clicks.append("reassert"))

    ea.fill_and_submit(page, plan=None, dry_run=False)

    assert page.clicks == ["reassert", ea.SEL_SUBMIT]
