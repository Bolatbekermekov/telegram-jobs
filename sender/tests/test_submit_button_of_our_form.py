"""Кнопка отправки — та, что у ЗАПОЛНЕННОЙ формы, а не первая похожая на странице.

Живьём 2026-09-22, лид #1520 (Teamtailor, leadtech.teamtailor.com): форма
открывается модалкой поверх страницы вакансии, и под `SEL_SUBMIT` на странице
подходят пять кнопок в таком порядке:

    0  <button type=submit> «Apply for this job»   — вне формы, открывает модалку
    1  <button type=submit> «Apply for this job»   — плавающая, тоже вне формы
    2  <button type=button> «Apply with LinkedIn»  — в форме заявки
    3  <input type=submit>  «Submit application»   — в форме заявки
    4  <button type=submit> «Log in»               — в форме входа кандидата

`submit.first` нажимал №0: модалка открывалась заново с пустой формой (резюме
пропало, поле CV снова `required`), заявка не ушла, а отчёт сказал «ВОЗМОЖНО,
ЗАЯВКА УЖЕ УШЛА, проверь почту».

JS проверяется там, где он работает, — на странице из замеренной разметки.
"""
import pytest

from app.infrastructure.channels import external_apply as ea

MARKUP = """
<main>
  <button type="submit" role="button">Apply for this job</button>
  <button type="submit" class="fixed">Apply for this job</button>
  <div class="modal">
    <form action="/applications" id="application">
      <button type="button" class="linkedin-button">Apply with LinkedIn</button>
      <input type="text" name="candidate[first_name]">
      <input type="email" name="candidate[email]">
      <textarea name="candidate[cover_letter]"></textarea>
      <input type="submit" name="commit" value="Submit application">
    </form>
  </div>
  <form action="/auto_join">
    <input type="email" aria-label="Email address without domain">
    <button type="submit" aria-label="Log in">Log in</button>
  </form>
</main>
"""


@pytest.fixture(scope="module")
def page():
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch(headless=True)
    except Exception as exc:  # noqa: BLE001 — no browser binary in this environment
        pw.stop()
        pytest.skip(f"chromium unavailable: {exc}")
    pg = browser.new_context().new_page()
    yield pg
    browser.close()
    pw.stop()


def _picked_label(page, markup):
    page.set_content(markup)
    ea.scrape_form(page)                 # ставит data-af, как перед заполнением
    btn = ea._submit_button(page)
    return btn.evaluate("el => (el.innerText || el.value || '').trim()")


def test_the_submit_of_the_filled_form_wins_over_an_earlier_apply_button(page):
    assert _picked_label(page, MARKUP) == "Submit application"


def test_a_page_whose_buttons_live_outside_any_form_keeps_the_first(page):
    """Ashby и прочие SPA держат кнопку вне <form>. Там выбирать не из чего, и
    порядок остаётся прежним — первая подходящая."""
    markup = """
      <div><input type="text" name="name"><input type="email" name="email"></div>
      <button type="button">Submit Application</button>
      <button type="button">Apply</button>"""
    assert _picked_label(page, markup) == "Submit Application"
