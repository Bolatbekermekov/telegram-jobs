"""Ответ-текст в выпадающем списке выбирается вариантом, а не роняет заполнение.

Живьём 2026-09-14 (лид #1216, LinkedIn Easy Apply, шаг 6/8): план нёс для
`select` строку «1 month» без номера варианта, `fill()` на списке бросал
исключение, и отклик уходил в ручной с «не смог заполнить обязательное поле» —
причина (ответ, которого нет в списке) при этом терялась.
"""
import pytest

from app.application.auto_apply import ApplyPlan, FillAction
from app.domain.channel import ManualApplyRequired
from app.domain.page_observation import FieldObs

OPTIONS = ["Select an option", "Immediate Joiner", "Less than 30 Days", "30 Days"]


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


def _select_page(page):
    page.set_content("""<body><label for="n">What is your current notice period?*</label>
      <select id="n" required data-af="0">
        <option value="" disabled selected>Select an option</option>
        <option value="1">Immediate Joiner</option>
        <option value="2">Less than 30 Days</option>
        <option value="3">30 Days</option>
      </select></body>""")


def _plan(value):
    field = FieldObs(tag="select", type="select-one", required=True, ref="0",
                     label="What is your current notice period?*", options=OPTIONS)
    return ApplyPlan(actions=[FillAction(field=field, value=value, source="custom")])


def test_a_text_answer_that_names_an_option_is_selected(page):
    from app.infrastructure.channels import external_apply as ea

    _select_page(page)
    ea.fill_fields(page, _plan("30 Days"))

    assert page.eval_on_selector("#n", "el => el.options[el.selectedIndex].text") == "30 Days"


def test_a_text_answer_missing_from_the_list_is_named(page):
    from app.infrastructure.channels import external_apply as ea

    _select_page(page)
    with pytest.raises(ManualApplyRequired, match="нет варианта «1 month»"):
        ea.fill_fields(page, _plan("1 month"))
