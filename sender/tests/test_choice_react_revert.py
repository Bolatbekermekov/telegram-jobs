"""Ответ, который страница сняла через полсекунды, не считается принятым.

Живьём 2026-09-14 (лид #1233, Modus Create на Greenhouse): вопрос «What type of
employment are you open to?» — группа из трёх галочек. Виджет кликал скриптом
(`el.click()`), видел отмеченную галочку и докладывал «выбрано». Замер с шагом
100 мс: галочка стоит 0–500 мс, на 600 мс React перерисовывает группу из своего
состояния, где ответа не было, и снимает её. Форма уходила с пустым обязательным
вопросом, отправка не проходила. Клик мышью по подписи React засчитывает —
галочка держалась все 4 секунды замера.

Разметка группы — с живой формы; скрипт повторяет измеренное поведение: клик
скриптом (`isTrusted === false`) снимается через 500 мс, клик мышью остаётся.
"""
import pytest

from app.infrastructure.channels.external_apply import scrape_form
from app.infrastructure.widgets.choice import pick_choice_reason

NAME = "question_32480382003[]"


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


def _option(n: str, label: str) -> str:
    return f"""
    <div><div><input description="What type of employment are you open to?" required=""
      type="checkbox" id="q_{n}" name="{NAME}" value="1687553{n}"></div>
      <label for="q_{n}">{label}</label></div>"""


GREENHOUSE = f"""
<form>
  <fieldset id="{NAME}" aria-required="true">
    <legend>What type of employment are you open to? <span>*</span></legend>
    {_option("87003", "Part-time")}{_option("88003", "Contract")}{_option("89003", "Full time employment")}
  </fieldset>
</form>
<script>
(() => {{
  for (const box of document.querySelectorAll('input[type=checkbox]')) {{
    box.addEventListener('click', e => {{
      if (!e.isTrusted) setTimeout(() => {{ box.checked = false; }}, 500);
    }});
  }}
}})();
</script>
"""


def _checked(page) -> list:
    return page.evaluate(
        """(n) => [...document.querySelectorAll('[name="' + n + '"]')]
                    .filter(e => e.checked).map(e => e.value)""", NAME)


def test_an_answer_the_page_takes_back_is_given_again_with_a_real_click(page):
    page.set_content(f"<body>{GREENHOUSE}</body>")
    group = next(f for f in scrape_form(page).fields if f.name == NAME)

    result = pick_choice_reason(page, page.locator(f'[data-af="{group.ref}"]'),
                                value="Full time employment", index=2)
    page.wait_for_timeout(1000)          # дольше, чем страница ждёт перед откатом

    assert result == (True, "")
    assert _checked(page) == ["168755389003"]
