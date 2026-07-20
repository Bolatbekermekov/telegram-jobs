import pytest

from app.domain.channel import ChannelError, OutreachContent, RateLimitedError
from app.infrastructure.channels.headhunter import (
    SEL_ALREADY_APPLIED,
    SEL_APPLY,
    SEL_CHAT_FILE_INPUT,
    SEL_CHAT_MSG,
    SEL_CHAT_OPEN_BTN,
    SEL_CHAT_SEND_ENABLED,
    SEL_LETTER_INPUT,
    SEL_LETTER_TOGGLE,
    SEL_COUNTRY_CONFIRM,
    SEL_QUESTIONS,
    SEL_SUBMIT,
    HeadHunterChannel,
    apply_via_page,
    attach_cv_via_chat,
    extract_vacancy_id,
    vacancy_url,
)


class _FakePage:
    """Maps selector -> element count; records goto/click/fill actions.

    Clicking the submit button removes it (models a successful send) unless
    submit_sticks=True (models a rejected form).
    """

    def __init__(self, counts, url="https://hh.ru/vacancy/1", submit_sticks=False,
                 body_text=""):
        self._counts = counts
        self.url = url
        self.actions = []
        self._submitted = False
        self._submit_sticks = submit_sticks
        self._body_text = body_text
        self.keyboard = _FakeKeyboard(self)

    def goto(self, url, **kw):
        self.actions.append(("goto", url))

    def inner_text(self, selector):
        return self._body_text

    def locator(self, selector):
        page = self

        class _Locator:
            def count(self_inner):
                if selector == SEL_SUBMIT and page._submitted and not page._submit_sticks:
                    return 0
                return page._counts.get(selector, 0)

            @property
            def first(self_inner):
                return self_inner

            @property
            def last(self_inner):
                return self_inner

            def nth(self_inner, i):
                return self_inner

            def click(self_inner, timeout=None):
                # Playwright raises when the element isn't there; the real submit
                # click is bounded, so the fake must be able to fail the same way.
                if page._counts.get(selector, 1) == 0:
                    raise TimeoutError(f"Locator.click: no {selector}")
                if selector == SEL_SUBMIT:
                    page._submitted = True
                    page.submit_timeout = timeout      # recorded, not in `actions`
                page.actions.append(("click", selector))

            def fill(self_inner, value):
                page.actions.append(("fill", selector, value))

            def check(self_inner):
                page.actions.append(("check", selector))

            def set_input_files(self_inner, path):
                page.actions.append(("set_input_files", selector, path))

            def press(self_inner, key):
                page.actions.append(("press", selector, key))

        return _Locator()

    def wait_for_selector(self, selector, **kw):
        self.actions.append(("wait", selector))

    def wait_for_timeout(self, ms):
        pass


class _FakeKeyboard:
    def __init__(self, page):
        self._page = page

    def press(self, key):
        self._page.actions.append(("press", key))


def test_extract_vacancy_id_from_url():
    assert extract_vacancy_id("https://hh.ru/vacancy/12345?from=x") == "12345"
    assert extract_vacancy_id("12345") == "12345"


def test_extract_vacancy_id_supports_hh_kz():
    assert extract_vacancy_id("https://hh.kz/vacancy/777") == "777"


def test_extract_vacancy_id_invalid():
    with pytest.raises(ChannelError):
        extract_vacancy_id("https://hh.ru/employer/9")


def test_vacancy_url_builds_canonical_link():
    assert vacancy_url("https://hh.kz/vacancy/777?from=x") == "https://hh.ru/vacancy/777"


def test_apply_fills_letter_and_submits():
    page = _FakePage({SEL_APPLY: 1, SEL_LETTER_TOGGLE: 1,
                      SEL_LETTER_INPUT: 1, SEL_SUBMIT: 1})
    apply_via_page(page, "https://hh.ru/vacancy/1", OutreachContent(body="Здравствуйте"))
    assert ("goto", "https://hh.ru/vacancy/1") in page.actions
    assert ("click", SEL_APPLY) in page.actions
    assert ("click", SEL_LETTER_TOGGLE) in page.actions
    assert ("fill", SEL_LETTER_INPUT, "Здравствуйте") in page.actions
    assert ("click", SEL_SUBMIT) in page.actions
    assert ("wait", f"{SEL_COUNTRY_CONFIRM}, {SEL_LETTER_TOGGLE}, {SEL_LETTER_INPUT}, "
            f"{SEL_ALREADY_APPLIED}") in page.actions


def test_apply_without_letter_toggle_fills_directly():
    # Some vacancies show the letter textarea right away (no toggle).
    page = _FakePage({SEL_APPLY: 1, SEL_LETTER_INPUT: 1, SEL_SUBMIT: 1})
    apply_via_page(page, "https://hh.ru/vacancy/2", OutreachContent(body="hi"))
    assert ("fill", SEL_LETTER_INPUT, "hi") in page.actions
    assert ("click", SEL_SUBMIT) in page.actions


def test_apply_confirms_country_popup_then_sends():
    # Vacancy in another country: hh shows a consent popup before the letter form.
    page = _FakePage({SEL_APPLY: 1, SEL_COUNTRY_CONFIRM: 1,
                      SEL_LETTER_INPUT: 1, SEL_SUBMIT: 1})
    apply_via_page(page, "https://hh.ru/vacancy/3", OutreachContent(body="hi"))
    assert ("click", SEL_COUNTRY_CONFIRM) in page.actions
    assert ("fill", SEL_LETTER_INPUT, "hi") in page.actions
    assert ("click", SEL_SUBMIT) in page.actions


def test_apply_one_click_no_letter_form_succeeds():
    # One-click-apply: no letter form renders; page shows an applied confirmation.
    # Must finish cleanly (no hang, no re-submit), not error.
    page = _FakePage({SEL_APPLY: 1}, body_text="Вы откликнулись на вакансию")
    apply_via_page(page, "https://hh.ru/vacancy/5", OutreachContent(body="hi"))
    assert ("click", SEL_APPLY) in page.actions
    assert not any(a[0] == "fill" for a in page.actions)   # no letter filled
    assert ("click", SEL_SUBMIT) not in page.actions        # nothing re-submitted


def test_apply_unknown_form_raises_instead_of_hanging():
    # No letter field and no applied confirmation -> clear error, not a 30s hang.
    page = _FakePage({SEL_APPLY: 1}, body_text="")
    with pytest.raises(ChannelError, match="поле письма"):
        apply_via_page(page, "https://hh.ru/vacancy/6", OutreachContent(body="hi"))


def test_apply_skips_vacancy_with_employer_questions():
    # Mandatory screening questions can't be auto-answered -> skip, don't submit.
    page = _FakePage({SEL_APPLY: 1, SEL_LETTER_TOGGLE: 1, SEL_QUESTIONS: 6,
                      SEL_LETTER_INPUT: 1, SEL_SUBMIT: 1})
    with pytest.raises(ChannelError, match="обязательными вопросами"):
        apply_via_page(page, "https://hh.ru/vacancy/9", OutreachContent(body="hi"))
    # no letter filled and no submit clicked
    assert not any(a[0] == "fill" for a in page.actions)
    assert ("click", SEL_SUBMIT) not in page.actions


def test_apply_answers_questions_with_answerer(monkeypatch):
    import app.infrastructure.channels.headhunter as hh

    questions = [
        {"id": "task_1", "type": "text", "prompt": "p", "options": []},
        {"id": "task_2", "type": "choice", "prompt": "p", "options": ["a", "b"]},
    ]
    monkeypatch.setattr(hh, "collect_questions", lambda page: questions)
    monkeypatch.setattr(hh, "_verify_submitted", lambda page: None)

    page = _FakePage({SEL_APPLY: 1, SEL_LETTER_TOGGLE: 1, SEL_QUESTIONS: 2,
                      SEL_LETTER_INPUT: 1, SEL_SUBMIT: 1,
                      "label:has(input[name='task_2'])": 2})

    def answerer(qs, vacancy):
        return {"task_1": {"id": "task_1", "text": "my answer"},
                "task_2": {"id": "task_2", "choice": 1}}

    apply_via_page(page, "https://hh.ru/vacancy/1", OutreachContent(body="letter"), answerer)
    assert ("fill", "textarea[name='task_1_text']", "my answer") in page.actions
    assert ("click", "label:has(input[name='task_2'])") in page.actions
    assert ("fill", SEL_LETTER_INPUT, "letter") in page.actions
    assert ("click", SEL_SUBMIT) in page.actions


def test_apply_fails_when_form_not_accepted():
    # Submit button still present after clicking = form rejected -> don't lie.
    page = _FakePage({SEL_APPLY: 1, SEL_LETTER_TOGGLE: 1, SEL_LETTER_INPUT: 1,
                      SEL_SUBMIT: 1}, submit_sticks=True)
    with pytest.raises(ChannelError, match="не подтверждён"):
        apply_via_page(page, "https://hh.ru/vacancy/1", OutreachContent(body="hi"))


def test_apply_raises_when_already_applied():
    page = _FakePage({SEL_ALREADY_APPLIED: 1})
    with pytest.raises(ChannelError, match="already applied"):
        apply_via_page(page, "https://hh.ru/vacancy/1", OutreachContent(body="hi"))


def test_apply_raises_without_apply_button():
    page = _FakePage({})
    with pytest.raises(ChannelError, match="нет кнопки отклика"):
        apply_via_page(page, "https://hh.ru/vacancy/1", OutreachContent(body="hi"))


class _Resp:
    def __init__(self, status):
        self.status = status


def test_inaccessible_vacancy_reports_the_http_status():
    """hh answers 403 for an archived or restricted vacancy (seen live on
    vacancy/133978075). Reporting "no apply button" there reads like a broken
    selector and sends you hunting through the DOM for nothing."""
    page = _FakePage({})
    page.goto = lambda url, **kw: _Resp(403)

    with pytest.raises(ChannelError, match="недоступна.*403"):
        apply_via_page(page, "https://hh.ru/vacancy/1", OutreachContent(body="hi"))


def test_a_200_response_proceeds_to_the_normal_checks():
    """The status guard must not swallow the ordinary path."""
    page = _FakePage({})
    page.goto = lambda url, **kw: _Resp(200)

    with pytest.raises(ChannelError, match="нет кнопки отклика"):
        apply_via_page(page, "https://hh.ru/vacancy/1", OutreachContent(body="hi"))


def test_login_redirect_raises_rate_limited():
    page = _FakePage({SEL_APPLY: 1}, url="https://hh.ru/account/login?backurl=%2F")
    with pytest.raises(RateLimitedError):
        apply_via_page(page, "https://hh.ru/vacancy/1", OutreachContent(body="hi"))


def test_channel_start_raises_without_state(tmp_path):
    # hh blocks the login request in launched browsers, so there is no
    # interactive fallback anymore — start() must point to `make login_hh`.
    ch = HeadHunterChannel(str(tmp_path / "missing.json"), headless=True)
    with pytest.raises(ChannelError, match="login_hh"):
        ch.start()


def test_channel_metadata():
    ch = HeadHunterChannel("hh.json", True)
    assert ch.name == "hh"
    assert ch.body_limit == 10000
    assert ch.needs_subject is False


# --- CV attachment in the chat ---------------------------------------------

def test_attach_cv_via_chat_sends_file():
    page = _FakePage({SEL_CHAT_OPEN_BTN: 1, SEL_CHAT_FILE_INPUT: 1, SEL_CHAT_SEND_ENABLED: 1})
    attach_cv_via_chat(page, "/cv/me.pdf")
    assert ("click", SEL_CHAT_OPEN_BTN) in page.actions
    assert ("set_input_files", SEL_CHAT_FILE_INPUT, "/cv/me.pdf") in page.actions
    assert ("click", SEL_CHAT_SEND_ENABLED) in page.actions


def test_attach_cv_via_chat_sends_letter_then_file():
    # One-click vacancies pass the letter here: it's typed and sent, then the PDF.
    page = _FakePage({SEL_CHAT_OPEN_BTN: 1, SEL_CHAT_MSG: 1,
                      SEL_CHAT_FILE_INPUT: 1, SEL_CHAT_SEND_ENABLED: 1})
    attach_cv_via_chat(page, "/cv/me.pdf", letter="Здравствуйте")
    assert ("fill", SEL_CHAT_MSG, "Здравствуйте") in page.actions
    assert ("set_input_files", SEL_CHAT_FILE_INPUT, "/cv/me.pdf") in page.actions


def test_attach_cv_via_chat_raises_without_open_button():
    page = _FakePage({})
    with pytest.raises(ChannelError, match="кнопка чата"):
        attach_cv_via_chat(page, "/cv/me.pdf")


def test_attach_cv_via_chat_raises_without_file_input():
    page = _FakePage({SEL_CHAT_OPEN_BTN: 1})
    with pytest.raises(ChannelError, match="поле файла"):
        attach_cv_via_chat(page, "/cv/me.pdf")


def test_apply_invokes_chat_attach_when_enabled(monkeypatch):
    import app.infrastructure.channels.headhunter as hh
    called = {}
    monkeypatch.setattr(hh, "attach_cv_via_chat",
                        lambda page, path, debug_dir=None, letter=None: called.setdefault("path", path))
    page = _FakePage({SEL_APPLY: 1, SEL_LETTER_TOGGLE: 1, SEL_LETTER_INPUT: 1, SEL_SUBMIT: 1})
    apply_via_page(page, "https://hh.ru/vacancy/1",
                   OutreachContent(body="hi", attachment_path="/cv/me.pdf"),
                   attach_cv_in_chat=True)
    assert called == {"path": "/cv/me.pdf"}


def test_apply_skips_chat_attach_without_attachment(monkeypatch):
    import app.infrastructure.channels.headhunter as hh
    called = {}
    monkeypatch.setattr(hh, "attach_cv_via_chat",
                        lambda *a, **k: called.setdefault("hit", True))
    page = _FakePage({SEL_APPLY: 1, SEL_LETTER_TOGGLE: 1, SEL_LETTER_INPUT: 1, SEL_SUBMIT: 1})
    apply_via_page(page, "https://hh.ru/vacancy/1", OutreachContent(body="hi"),
                   attach_cv_in_chat=True)  # no attachment_path
    assert called == {}


def test_apply_survives_chat_attach_failure(monkeypatch):
    # Attaching the CV in chat failing must NOT fail the (already sent) application.
    import app.infrastructure.channels.headhunter as hh

    def boom(page, path, debug_dir=None, letter=None):
        raise ChannelError("chat selector drifted")

    monkeypatch.setattr(hh, "attach_cv_via_chat", boom)
    page = _FakePage({SEL_APPLY: 1, SEL_LETTER_TOGGLE: 1, SEL_LETTER_INPUT: 1, SEL_SUBMIT: 1})
    # Should return normally (no raise).
    apply_via_page(page, "https://hh.ru/vacancy/1",
                   OutreachContent(body="hi", attachment_path="/cv/me.pdf"),
                   attach_cv_in_chat=True)
    assert ("click", SEL_SUBMIT) in page.actions


# --- regional HeadHunter domains --------------------------------------------

def test_regional_link_is_rewritten_to_the_session_domain():
    """Cookies from `make login_hh` are hh.ru-only; opening hh.kz browses
    anonymously and dead-ends at the login wall on Apply (verified live)."""
    from app.infrastructure.channels.headhunter import to_session_domain

    assert to_session_domain("https://hh.kz/vacancy/135297431?from=share_ios") == \
        "https://hh.ru/vacancy/135297431?from=share_ios"


def test_regional_subdomain_is_rewritten_too():
    from app.infrastructure.channels.headhunter import to_session_domain

    assert to_session_domain("https://astana.hh.kz/vacancy/1") == "https://hh.ru/vacancy/1"


def test_hh_ru_link_is_left_alone():
    from app.infrastructure.channels.headhunter import to_session_domain

    url = "https://hh.ru/vacancy/1?query=x"
    assert to_session_domain(url) == url


def test_a_foreign_host_is_not_rewritten():
    """Guard the regex: only HeadHunter's own domains get rebased."""
    from app.infrastructure.channels.headhunter import to_session_domain

    url = "https://not-hh.kz/vacancy/1"
    assert to_session_domain(url) == url


# --- chat entry point --------------------------------------------------------

def test_chat_opener_accepts_the_post_response_button():
    """hh stopped rendering `open-vacancy-chat`; after a response the chat opens
    from `vacancy-response-link-view-topic` (verified live on vacancy/135297431,
    where the old selector matched 0 and the new one 2). Without this the CV was
    never delivered — the application went through, the attachment did not."""
    from app.infrastructure.channels.headhunter import SEL_CHAT_OPEN_BTN

    assert "vacancy-response-link-view-topic" in SEL_CHAT_OPEN_BTN
    assert "open-vacancy-chat" in SEL_CHAT_OPEN_BTN     # kept as the first choice


def test_attach_cv_opens_the_chat_via_the_post_response_button():
    """A page that only has the new button must still reach the file input."""
    from app.infrastructure.channels.headhunter import (
        SEL_CHAT_FILE_INPUT, SEL_CHAT_OPEN_BTN, attach_cv_via_chat,
    )

    page = _FakePage({SEL_CHAT_OPEN_BTN: 1, SEL_CHAT_FILE_INPUT: 1})
    attach_cv_via_chat(page, "C:/cv.pdf")

    assert ("click", SEL_CHAT_OPEN_BTN) in page.actions
    assert ("set_input_files", SEL_CHAT_FILE_INPUT, "C:/cv.pdf") in page.actions


def test_attach_cv_reports_when_no_chat_button_exists_at_all():
    from app.infrastructure.channels.headhunter import attach_cv_via_chat

    page = _FakePage({})
    with pytest.raises(ChannelError, match="кнопка чата"):
        attach_cv_via_chat(page, "C:/cv.pdf")


# --- hh quick apply (response sent on the Apply click) -----------------------

def test_quick_apply_is_not_reported_as_failed():
    """hh sends the response on the Apply click, then offers a cover-letter popup
    whose submit control is not `vacancy-response-submit-popup`. Checking the
    letter form before the applied-state made us fill that popup, time out on a
    missing button, and mark a sent application `failed` (live: vacancy/135269482)."""
    from app.infrastructure.channels.headhunter import (
        SEL_ALREADY_APPLIED, SEL_APPLY, SEL_LETTER_INPUT, apply_via_page,
    )

    # Apply button present, response already registered, and a letter popup open.
    page = _FakePage({SEL_APPLY: 1, SEL_ALREADY_APPLIED: 0, SEL_LETTER_INPUT: 1})
    original = page.locator

    def _locator(sel):
        # After the apply click hh marks the vacancy as responded.
        if ("click", SEL_APPLY) in page.actions:
            page._counts[SEL_ALREADY_APPLIED] = 1
        return original(sel)

    page.locator = _locator
    apply_via_page(page, "https://hh.ru/vacancy/1", OutreachContent(body="hi"))

    # Never hunted for the submit button, never reported a failure.
    assert not any(a[0] == "click" and SEL_SUBMIT in str(a) for a in page.actions)


def test_submit_click_failure_rechecks_before_declaring_failure():
    """Belt and braces: if the click does fail, a response that went through
    anyway must not be reported as an error."""
    from app.infrastructure.channels.headhunter import (
        SEL_ALREADY_APPLIED, SEL_APPLY, SEL_LETTER_INPUT, apply_via_page,
    )

    page = _FakePage({SEL_APPLY: 1, SEL_LETTER_INPUT: 1, SEL_SUBMIT: 0,
                      SEL_ALREADY_APPLIED: 0})
    original = page.locator

    def _locator(sel):
        # The response lands while the letter popup is still open.
        if ("fill", SEL_LETTER_INPUT, "hi") in page.actions:
            page._counts[SEL_ALREADY_APPLIED] = 1
        return original(sel)

    page.locator = _locator
    apply_via_page(page, "https://hh.ru/vacancy/1", OutreachContent(body="hi"))


def test_unknown_popup_without_a_response_still_fails_loudly():
    """The recheck must not turn every broken layout into a silent success."""
    from app.infrastructure.channels.headhunter import (
        SEL_APPLY, SEL_LETTER_INPUT, apply_via_page,
    )

    page = _FakePage({SEL_APPLY: 1, SEL_LETTER_INPUT: 1, SEL_SUBMIT: 0})
    with pytest.raises(ChannelError, match="кнопка отправки"):
        apply_via_page(page, "https://hh.ru/vacancy/1", OutreachContent(body="hi"))

# --- the cover letter must not depend on the CV setting ---------------------

def test_letter_is_sent_even_when_cv_attaching_is_off():
    """The letter is the point of the tool. Gating it on the CV switch meant
    turning off the PDF silently dropped the letter on quick-apply vacancies,
    where the chat is the only way it reaches the employer."""
    from app.infrastructure.channels.headhunter import (
        SEL_CHAT_FILE_INPUT, SEL_CHAT_MSG, SEL_CHAT_OPEN_BTN, _maybe_attach_cv,
    )

    page = _FakePage({SEL_CHAT_OPEN_BTN: 1, SEL_CHAT_MSG: 1, SEL_CHAT_FILE_INPUT: 1})
    content = OutreachContent(body="hi", attachment_path="C:/cv.pdf")

    _maybe_attach_cv(page, content, attach_cv_in_chat=False, debug_dir=None,
                     letter="Здравствуйте, меня заинтересовала вакансия")

    assert ("fill", SEL_CHAT_MSG, "Здравствуйте, меня заинтересовала вакансия") in page.actions
    # CV explicitly disabled -> the PDF must not be uploaded.
    assert not any(a[0] == "set_input_files" for a in page.actions)


def test_letter_and_cv_both_go_when_enabled():
    from app.infrastructure.channels.headhunter import (
        SEL_CHAT_FILE_INPUT, SEL_CHAT_MSG, SEL_CHAT_OPEN_BTN, _maybe_attach_cv,
    )

    page = _FakePage({SEL_CHAT_OPEN_BTN: 1, SEL_CHAT_MSG: 1, SEL_CHAT_FILE_INPUT: 1})
    content = OutreachContent(body="hi", attachment_path="C:/cv.pdf")

    _maybe_attach_cv(page, content, attach_cv_in_chat=True, debug_dir=None, letter="письмо")

    assert ("fill", SEL_CHAT_MSG, "письмо") in page.actions
    assert ("set_input_files", SEL_CHAT_FILE_INPUT, "C:/cv.pdf") in page.actions


def test_nothing_is_opened_when_there_is_neither_letter_nor_cv():
    from app.infrastructure.channels.headhunter import SEL_CHAT_OPEN_BTN, _maybe_attach_cv

    page = _FakePage({SEL_CHAT_OPEN_BTN: 1})
    _maybe_attach_cv(page, OutreachContent(body="hi"), attach_cv_in_chat=True,
                     debug_dir=None, letter=None)
    assert page.actions == []


def test_a_failed_letter_is_reported_loudly(capsys):
    """A delivered application with no letter is the failure mode that matters."""
    from app.infrastructure.channels.headhunter import _maybe_attach_cv

    page = _FakePage({})           # no chat button at all -> chat step raises
    _maybe_attach_cv(page, OutreachContent(body="hi"), attach_cv_in_chat=False,
                     debug_dir=None, letter="письмо")

    out = capsys.readouterr().out
    assert "ПИСЬМО НЕ ДОШЛО" in out


def test_submit_wait_is_configurable():
    """Tunable from .env: a slow popup should get room to render without editing code."""
    from app.infrastructure.channels.headhunter import (
        SEL_APPLY, SEL_LETTER_INPUT, SUBMIT_TIMEOUT_MS, apply_via_page,
    )

    assert SUBMIT_TIMEOUT_MS == 100_000
    page = _FakePage({SEL_APPLY: 1, SEL_LETTER_INPUT: 1, SEL_SUBMIT: 1})
    apply_via_page(page, "https://hh.ru/vacancy/1", OutreachContent(body="hi"),
                   submit_timeout_ms=45_000)
    assert page.submit_timeout == 45_000


def test_the_channel_passes_its_configured_wait_through():
    from app.infrastructure.channels.headhunter import HeadHunterChannel

    ch = HeadHunterChannel("/nonexistent", submit_timeout_ms=12_345)
    assert ch._submit_timeout_ms == 12_345
