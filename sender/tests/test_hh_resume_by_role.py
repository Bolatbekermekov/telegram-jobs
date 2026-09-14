"""Отклик на hh уходит с онлайн-резюме той роли, под которую написано письмо.

До 2026-09-14 в аккаунте было одно резюме — «Golang-разработчик», и все отклики,
включая AI-вакансии, уходили с ним (PDF под роль попадал только в чат).
Владелец разрешил завести резюме под роли; с двумя и больше резюме hh перед
отправкой показывает окно «Vacancy response» с выбором резюме.

Разметка окна снята живьём 2026-09-14 (вакансия 137163618, ничего не отправлено):
карточка `[role=button]` с `[data-qa=resume-title]`, по клику — список
`label[role=option][data-qa=magritte-select-option-<id резюме>]` с текстом
«<название> <зарплата>»; письмо раскрывает `[data-qa=add-cover-letter]`, и только
тогда появляется `vacancy-response-popup-form-letter-input`.
"""
import pytest

from app.domain.channel import ChannelError, OutreachContent
from app.domain.hh_resume import hh_resume_title, parse_role_titles

TITLES = {"ai": "AI-инженер (LLM, Python)", "backend-go": "Golang-разработчик"}
AI_CV = "/Users/x/telegram-jobs/sender/cv/ai/Bolatbek_Yermekov_AI_Engineer.pdf"


# --- какое резюме под какую роль ---------------------------------------------

def test_titles_are_read_from_the_setting():
    raw = "ai=AI-инженер (LLM, Python); qa = Тестировщик-автоматизатор ;broken;devops=X"
    assert parse_role_titles(raw) == {"ai": "AI-инженер (LLM, Python)",
                                      "qa": "Тестировщик-автоматизатор"}


def test_the_title_follows_the_role_folder_of_the_attached_cv():
    assert hh_resume_title(AI_CV, TITLES) == "AI-инженер (LLM, Python)"
    assert hh_resume_title("/s/cv/frontend/Bolatbek_Yermekov_Frontend.pdf", TITLES) == ""
    assert hh_resume_title(None, TITLES) == ""
    assert hh_resume_title(AI_CV, {}) == ""


# --- окно отклика: живая разметка --------------------------------------------

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


def _popup(ai_hidden: bool = False) -> str:
    warning_height = "40px" if ai_hidden else "0px"
    return f"""<body><div role="dialog">
  <div data-qa="hidden-resume-warning" id="warn"
       style="max-height:0px; height:0px; overflow:hidden">Чтобы откликнуться на эту
    вакансию, поменяйте видимость резюме</div>
  <div role="button" tabindex="0" onclick="document.getElementById('list').hidden = false">
    <div data-qa="resume-title"><div data-qa="cell-text-content" id="t">Golang-разработчик</div></div>
    <div data-qa="resume-detail">500 $</div>
  </div>
  <div id="list" hidden data-qa="magritte-select-option-list">
    <label role="option" aria-selected="false" data-qa="magritte-select-option-ae8fa9caff"
      onclick="document.getElementById('t').textContent = 'AI-инженер (LLM, Python)';
               document.getElementById('warn').style.maxHeight = '{warning_height}';
               document.getElementById('warn').style.height = '{warning_height}';
               document.getElementById('list').hidden = true">AI-инженер (LLM, Python) 500 $</label>
    <label role="option" aria-selected="true" data-qa="magritte-select-option-73b51422ff"
      onclick="document.getElementById('t').textContent = 'Golang-разработчик';
               document.getElementById('list').hidden = true">Golang-разработчик 500 $</label>
  </div>
  <button type="button" data-qa="add-cover-letter">Add a CV</button>
  <button type="submit" data-qa="vacancy-response-submit-popup">Send application</button>
</div></body>"""


def _title(page) -> str:
    return page.inner_text("[data-qa='resume-title']").strip()


def test_the_resume_of_the_role_is_picked_in_the_response_window(page):
    from app.infrastructure.channels import headhunter as hh

    page.set_content(_popup())

    assert hh._choose_resume(page, "AI-инженер (LLM, Python)") is True
    assert _title(page) == "AI-инженер (LLM, Python)"


def test_an_already_chosen_resume_is_left_alone(page):
    from app.infrastructure.channels import headhunter as hh

    page.set_content(_popup())

    assert hh._choose_resume(page, "Golang-разработчик") is True
    assert page.is_hidden("#list"), "список даже не открывали"


def test_a_resume_missing_from_the_account_keeps_the_default(page):
    from app.infrastructure.channels import headhunter as hh

    page.set_content(_popup())

    assert hh._choose_resume(page, "Frontend-разработчик") is False
    assert _title(page) == "Golang-разработчик"
    assert page.is_visible("[data-qa='vacancy-response-submit-popup']"), "окно не закрыто"


def test_a_resume_hidden_from_employers_stops_the_response(page):
    from app.infrastructure.channels import headhunter as hh

    page.set_content(_popup(ai_hidden=True))

    with pytest.raises(ChannelError, match="видимост"):
        hh._choose_resume(page, "AI-инженер (LLM, Python)")


def test_the_letter_opens_through_add_cover_letter():
    from app.infrastructure.channels import headhunter as hh

    assert "add-cover-letter" in hh.SEL_LETTER_TOGGLE


# --- проводка ------------------------------------------------------------------

def test_apply_picks_the_resume_before_writing_the_letter(monkeypatch):
    import app.infrastructure.channels.headhunter as hh
    from tests.test_headhunter_channel import _FakePage

    page = _FakePage({hh.SEL_APPLY: 1, hh.SEL_LETTER_TOGGLE: 1, hh.SEL_LETTER_INPUT: 1,
                      hh.SEL_SUBMIT: 1})
    monkeypatch.setattr(hh, "_verify_submitted", lambda page, debug_dir=None: None)
    monkeypatch.setattr(hh, "_choose_resume",
                        lambda pg, title: pg.actions.append(("resume", title)) or True)

    hh.apply_via_page(page, "https://hh.ru/vacancy/1", OutreachContent(body="letter"),
                      resume_title="AI-инженер (LLM, Python)")

    assert ("resume", "AI-инженер (LLM, Python)") in page.actions
    assert page.actions.index(("resume", "AI-инженер (LLM, Python)")) \
        < page.actions.index(("fill", hh.SEL_LETTER_INPUT, "letter"))


def test_the_channel_sends_the_title_of_the_letters_role(monkeypatch):
    import app.infrastructure.channels.headhunter as hh

    seen = {}
    monkeypatch.setattr(hh, "apply_via_page",
                        lambda *args, **kwargs: seen.update(title=kwargs.get("resume_title")))
    channel = hh.HeadHunterChannel("/state.json", resume_titles=TITLES)
    channel._page = object()

    channel.send("https://hh.ru/vacancy/1", OutreachContent(body="x", attachment_path=AI_CV))

    assert seen["title"] == "AI-инженер (LLM, Python)"
