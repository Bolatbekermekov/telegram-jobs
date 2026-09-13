"""LinkedIn на английском: новый аккаунт 2026-09-13 и новая вёрстка ленты.

Прогон 2026-09-13 шёл с нового аккаунта с английским интерфейсом, и три класса
отказов дали 14 лидов из 65. Всё ниже снято живьём в тот же день на той же
сессии; разметка упрощена, но теги, атрибуты и тексты — как на странице.

1. Окно приглашения. После Connect английский LinkedIn показывает «Add a note to
   your invitation?» с кнопками «Add a note» и «Send without a note». Код ждал
   «Personalize» (и русское «Персонализировать»), не находил и объявлял, что окно
   не открылось: 10 лидов `failed` при открытом окне.
2. Автор поста. Лента теперь без говорящих классов: ни
   `update-components-actor__meta-link`, ни `data-view-name`. Старый селектор
   находил 0 элементов, и три поста ушли в `failed` «не удалось определить
   автора». Устойчиво одно: карточка поста — `div[role=listitem]` с
   `componentkey`, начинающимся на `update-card`, и первая ссылка на профиль или
   страницу в ней — автор. Ссылки ВНЕ карточки (подсказки поиска, свой профиль в
   шапке) стоят в разметке раньше, и «первая на странице» — не автор.
3. Ошибка поля Easy Apply. Английский аккаунт пишет под полем «Invalid input», а
   распознавались только «Недопустимое значение» и «invalid value». Обход шесть
   раз подряд жал Review по одному экрану (лид #1001).
"""
import pytest

from app.infrastructure.channels.linkedin import (
    SEL_PERSONALIZE, SEL_POST_ACTOR, _first_field_error,
)


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


def show(page, html):
    page.set_content(f"<body>{html}</body>")


# --- окно приглашения -------------------------------------------------------------

_INVITE_EN = """
<div role="dialog" aria-labelledby="send-invite-modal">
  <h2 id="send-invite-modal">Add a note to your invitation?</h2>
  <p>Personalize your invitation to Nazira Idrissova by adding a note.</p>
  <button aria-label="Dismiss"></button>
  <button aria-label="Add a note">Add a note</button>
  <button aria-label="Send without a note">Send without a note</button>
</div>
"""
_INVITE_RU = """
<div role="dialog">
  <button>Персонализировать</button>
  <button>Отправить без заметки</button>
</div>
"""


def test_the_english_invite_modal_is_recognised(page):
    show(page, _INVITE_EN)
    assert page.locator(SEL_PERSONALIZE).count() == 1


def test_the_russian_invite_modal_still_is(page):
    show(page, _INVITE_RU)
    assert page.locator(SEL_PERSONALIZE).count() == 1


# --- автор поста -------------------------------------------------------------------

_POST_PAGE = """
<div role="dialog">
  <a href="https://www.linkedin.com/in/dilnaz-alimbayeva-6ab6351b8/">Dilnaz Alimbayeva • 1st</a>
</div>
<header><a href="https://www.linkedin.com/in/bolatbekermekov/">Me</a></header>
<div data-lazy-mount-id="8lpww">
  <div role="listitem" componentkey="update-card-focuspsKxx8jSZDdAHsPj9Rl4l1tO5DxADOwjr31ZQ58zF7cFeedType_FEED_DETAIL">
    <div componentkey="psKxx8jSZDdAHsPj9Rl4l1tO5DxADOwjr31ZQ58zF7c">
      <a tabindex="0" href="https://www.linkedin.com/company/kake/" componentkey="05d52ee8"><img alt="Kake"></a>
      <a tabindex="0" href="https://www.linkedin.com/company/kake/" componentkey="2cb4d022">Kake</a>
    </div>
    <p>Plot twist: the best part of your 2026 might be…</p>
    <a href="https://www.linkedin.com/in/akhtarali-mern/">Akhtar Ali</a>
  </div>
</div>
"""


def test_the_post_author_is_the_first_link_inside_the_post_card(page):
    show(page, _POST_PAGE)
    assert page.locator(SEL_POST_ACTOR).first.get_attribute("href") == \
        "https://www.linkedin.com/company/kake/"


def test_a_person_author_is_found_the_same_way(page):
    show(page, _POST_PAGE.replace("/company/kake/", "/in/hr-lead-example/"))
    assert page.locator(SEL_POST_ACTOR).first.get_attribute("href") == \
        "https://www.linkedin.com/in/hr-lead-example/"


# --- ошибка поля Easy Apply ------------------------------------------------------

_NUMERIC_EN = """
  <input required id="«r11»" aria-describedby="«r11»-info"
         aria-label="Is your overall education percentages from 10th to Bachelors / Masters are all above 80% scores ?"
         type="text" value="Yes">
  <div data-testid="text-input-helper-text" id="«r11»-info"><p>Invalid input</p></div>
"""
_COUNTER_EN = """
  <input required id="«r12»" aria-describedby="«r12»-info"
         aria-label="How many years of work experience do you have with Python?" type="text" value="3">
  <div data-testid="text-input-helper-text" id="«r12»-info"><p>1/20</p></div>
"""


def test_an_english_invalid_input_is_found_and_names_the_field(page):
    show(page, _COUNTER_EN + _NUMERIC_EN)
    said = _first_field_error(page)
    assert "education percentages" in said
    assert "Invalid input" in said


def test_a_plain_character_counter_is_not_an_error(page):
    show(page, _COUNTER_EN)
    assert _first_field_error(page) == ""
