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


# --- телефон рядом со списком кодов стран -------------------------------------
# Живьём 2026-09-16, прогон 15 (лид #1301, Workable valsoft-corp): отклик уехал в
# ручные с «ответ ИИ содержит личные данные ['phone'] (поле
# «*Phone+7United States+1United Kingdom+44Canada+1Germany+49…»)». Подпись поля —
# это весь список кодов стран: <label> оборачивает и телефонный вход, и <select>
# с сотнями <option>, а подпись берётся как textContent целиком. Из-за мусорной
# подписи правило не узнало в поле телефон, вопрос уехал модели, та написала
# номер владельца — и страж личных данных остановил уже заполненную форму.
WORKABLE_PHONE = """
<label for="phone">Phone*
  <select name="country">
    <option>+7 United States</option>
    <option>+1 United Kingdom</option>
    <option>+44 Canada</option>
  </select>
  <input id="phone" name="phone" type="tel">
</label>
"""


def test_a_country_code_list_does_not_become_the_phone_label(page):
    obs = scrape(page, WORKABLE_PHONE)

    phone = [f for f in obs.fields if f.name == "phone"][0]
    assert "United States" not in phone.label
    assert phone.label.startswith("Phone")


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


# --- приманка для ботов у Teamtailor -----------------------------------------
# Живьём 2026-09-15, лиды #1273 и #1274 (Transcendent Group и Advisense, форма
# Teamtailor на career.advisense.com): рядом с настоящим «Email» лежит
# `<input type=email name=full_email required tabindex=-1 autocomplete=off>` с
# подписью «Email address without domain» и opacity 0. Человек его не видит и не
# попадёт в него с клавиатуры — это приманка: заявку, где оно заполнено, форма
# считает спамом. Скрапер принимал его за обязательное поле, и оба отклика ушли в
# ручные с «не смог заполнить обязательное поле».
TEAMTAILOR_HONEYPOT = """
<label for="candidate_email">Email</label>
<input type="email" id="candidate_email" name="candidate[email]" required>
<div class="flex items-center justify-between leading-tight text-md">
  <label for="full_email">Email address without domain</label>
  <input type="email" name="full_email" id="full_email" required tabindex="-1"
         autocomplete="off" style="opacity:0; position:absolute; width:500px; height:48px">
</div>
"""


def test_a_honeypot_field_is_not_a_field(page):
    obs = scrape(page, TEAMTAILOR_HONEYPOT)
    assert [f.name for f in obs.fields] == ["candidate[email]"]


def test_a_see_through_consent_switch_is_still_a_field(page):
    """Прозрачность сама по себе не приманка: переключатели согласия у той же
    Teamtailor рисуют настоящий checkbox с opacity 0 под своей картинкой, и в него
    можно попасть с клавиатуры."""
    obs = scrape(page, '<label class="label-switch"><input type="checkbox" '
                       'name="consent" required style="opacity:0; position:absolute">'
                       ' I agree to the privacy policy</label>')
    assert [f.name for f in obs.fields] == ["consent"]


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


# --- предел длины, объявленный не атрибутом ----------------------------------
# LinkedIn Easy Apply не ставит `maxlength`: предел живёт в подсказке поля —
# «Использовано: 37 из 20 символов», — и превышение отзывается там же
# «Недопустимым значением», без единого `role=alert`. Не прочитав предел, модель
# отвечает фразой в поле на двадцать знаков, экран молча не сменяется, и обход
# упирается в предел шагов (живьём 2026-09-05, вакансия 4461771754).
LINKEDIN_LIMITED = """
  <input required id="q-salary" aria-describedby="q-salary-info"
         aria-label="What is your current salary ?" type="text">
  <div id="q-salary-info">1/20 Использовано: 1 из 20 символов</div>
"""


def test_the_limit_is_read_from_the_hint_when_there_is_no_maxlength(page):
    obs = scrape(page, LINKEDIN_LIMITED)
    [fld] = [f for f in obs.fields if "salary" in f.label]
    assert fld.max_len == 20


def test_a_real_maxlength_still_wins(page):
    obs = scrape(page, '<input maxlength="7" aria-label="Код">')
    [fld] = [f for f in obs.fields if f.label == "Код"]
    assert fld.max_len == 7


def test_english_wording_of_the_hint_counts(page):
    obs = scrape(page, """
      <input id="e" aria-describedby="e-info" aria-label="About you">
      <div id="e-info">0 of 300 characters</div>
    """)
    [fld] = [f for f in obs.fields if f.label == "About you"]
    assert fld.max_len == 300


def test_no_declared_limit_reads_as_zero(page):
    obs = scrape(page, '<input aria-label="Свободное поле">')
    [fld] = [f for f in obs.fields if f.label == "Свободное поле"]
    assert fld.max_len == 0
