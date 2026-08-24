"""Чтение полей формы — на разметке, снятой с живых ATS 2026-08-24.

Скрапер (`_SCRAPE_JS`) до сих пор не был покрыт тестами: фейковая страница в
`test_external_apply.py` подменяет `page.evaluate` и до самого JS не доходит.
Прогон по Remocate показал, чего это стоило — три формы открылись и ни одна не
заполнилась, потому что поля читались неправильно.

Браузер настоящий, но сеть не нужна: разметка подаётся через `set_content`,
поэтому тест детерминированный и в живую метку `live` не попадает.
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
    page = browser.new_context().new_page()
    yield page
    browser.close()
    p.stop()


def scrape(page, html):
    page.set_content(f"<body>{html}</body>")
    return scrape_form(page)


# --- служебное поле react-select ---------------------------------------------
# Новая форма Greenhouse рисует каждый выпадающий вопрос ПАРОЙ: настоящий
# `role=combobox` с подписью и второй, безымянный вход, который существует только
# чтобы браузер ругался на пустой выбор. Замер на вакансии N26 (job_app?for=n26):
# 26 «полей» вместо 13 вопросов, у каждого второго подпись пустая — и именно они
# попали в «не заполнены обязательные поля», сорвав отправку.
#
# Сам Greenhouse помечает такой вход `aria-hidden="true"`, то есть говорит
# явно: это не поле для человека. На этом признаке правило и стоит — не на
# «подпись пустая», которая бывает и у настоящего поля.
GREENHOUSE_SELECT = """
<label for="country">Country*</label>
<div class="select">
  <input role="combobox" id="country" class="select__input" aria-required="true">
  <input required tabindex="-1" aria-hidden="true"
         class="remix-css-1a0ro4n-requiredInput" value="">
</div>
"""


def test_the_hidden_twin_of_a_combobox_is_not_a_field(page):
    obs = scrape(page, GREENHOUSE_SELECT)
    assert [f.label for f in obs.fields] == ["Country*"]
    assert obs.fields[0].combobox is True
    assert obs.fields[0].required is True


def test_an_aria_hidden_file_input_is_still_a_field(page):
    """Исключение по `aria-hidden` не должно задеть загрузку резюме: почти каждый
    ATS прячет настоящий `input[type=file]` за своей кнопкой, и на этом уже
    обжигались — заявка ушла без резюме."""
    obs = scrape(page, '<input type="file" name="resume" aria-hidden="true" '
                       'aria-label="Resume">')
    assert [f.name for f in obs.fields] == ["resume"]


# --- группа чекбоксов --------------------------------------------------------
# Lever задаёт вопрос с несколькими ответами набором чекбоксов под одним `name`.
# Замер на вакансии CoinsPaid: «React 16 or earlier», «React 17+», «React 18+»,
# «No experience with React» приехали как ЧЕТЫРЕ отдельных обязательных поля, у
# каждого вместо вопроса стоял его же вариант. Ответить на такое нечем, и отклик
# ушёл в ручной. Радиокнопки этот код уже группирует — чекбоксы нет.
LEVER_CHECKBOXES = """
<div class="application-question">
  <div class="text">Which React versions have you worked with?</div>
  <ul>
    <li><label><input type="checkbox" name="cards[abc][values]" required> React 16 or earlier</label></li>
    <li><label><input type="checkbox" name="cards[abc][values]" required> React 17+</label></li>
    <li><label><input type="checkbox" name="cards[abc][values]" required> React 18+</label></li>
  </ul>
</div>
"""


def test_a_checkbox_group_is_one_question(page):
    obs = scrape(page, LEVER_CHECKBOXES)
    assert len(obs.fields) == 1
    f = obs.fields[0]
    assert f.type == "checkbox"
    assert f.label == "Which React versions have you worked with?"
    assert f.options == ["React 16 or earlier", "React 17+", "React 18+"]
    assert f.required is True


def test_a_lone_checkbox_keeps_its_sentence_as_the_label(page):
    """Согласие — не группа, и его подпись это ВОПРОС, а не ответ. Правило про
    группы не должно его переехать: раньше «Yes» вместо согласия оставляло
    галочку непоставленной, и форма не пускала дальше."""
    obs = scrape(page, """
      <div><p>Acme has my consent to process my data*</p>
      <label><input type="checkbox" name="consent"> Yes</label></div>""")
    assert len(obs.fields) == 1
    assert obs.fields[0].options == []
    assert "consent to process my data" in obs.fields[0].label


def test_radio_groups_still_work(page):
    """Существующее поведение не должно поехать вместе с чекбоксами."""
    obs = scrape(page, """
      <fieldset><legend>Gender</legend>
        <label><input type="radio" name="g" value="m"> Male</label>
        <label><input type="radio" name="g" value="f"> Female</label>
      </fieldset>""")
    assert len(obs.fields) == 1
    assert obs.fields[0].label == "Gender"
    assert obs.fields[0].options == ["Male", "Female"]
