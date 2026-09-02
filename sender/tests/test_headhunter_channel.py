import pytest

from app.domain.channel import ChannelError, OutreachContent, RateLimitedError
from app.infrastructure.channels.headhunter import (
    SEL_ALREADY_APPLIED,
    SEL_APPLY,
    SEL_CHAT_FILE_INPUT,
    SEL_CHAT_MSG,
    SEL_CHAT_ADD_LETTER,
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
                 body_text="", intercepted=()):
        self._counts = counts
        # Селекторы, клик по которым съедает оверлей — ровно так вела себя
        # модалка отклика 2026-08-23: элемент есть, видим и стабилен, а клик
        # отваливается по таймауту.
        self._intercepted = set(intercepted)
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
                if selector in page._intercepted:
                    raise TimeoutError(
                        f"Locator.click: Timeout 30000ms exceeded ({selector}) — "
                        "modal-overlay intercepts pointer events")
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

            def evaluate(self_inner, expr, timeout=None):
                # Нативный el.click(): оверлей ему не мешает, хит-теста нет.
                page.actions.append(("jsclick", selector))
                # hh раскрывает композер только по ссылке «Add a cover letter»:
                # до неё поля сообщения на странице чата нет вовсе.
                if selector == SEL_CHAT_ADD_LETTER:
                    page._counts[SEL_CHAT_MSG] = 1
                    page._counts[SEL_CHAT_SEND_ENABLED] = 1

        return _Locator()

    def wait_for_selector(self, selector, **kw):
        self.actions.append(("wait", selector))

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, expr):
        # _neutralize_cookie_banner runs page.evaluate(...) to hide the banner.
        self.actions.append(("evaluate",))


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


def test_apply_neutralizes_cookie_banner_before_the_letter_toggle():
    """The cookie banner overlays the letter toggle; clearing it is what stopped
    'поле письма не появилось' when the toggle click was being swallowed."""
    page = _FakePage({SEL_APPLY: 1, SEL_LETTER_TOGGLE: 1,
                      SEL_LETTER_INPUT: 1, SEL_SUBMIT: 1})
    apply_via_page(page, "https://hh.ru/vacancy/1", OutreachContent(body="hi"))
    assert ("evaluate",) in page.actions
    # It runs before the toggle click, not after.
    assert page.actions.index(("evaluate",)) < page.actions.index(("click", SEL_LETTER_TOGGLE))


def test_chat_neutralizes_cookie_banner_before_sending_the_letter():
    """Row #101/#103: the letter never reached the chat because the banner
    intercepted the message-field click. Clear it first."""
    page = _FakePage({SEL_CHAT_OPEN_BTN: 1, SEL_CHAT_MSG: 1, SEL_CHAT_SEND_ENABLED: 1})
    attach_cv_via_chat(page, None, None, letter="Здравствуйте")
    assert ("evaluate",) in page.actions
    assert ("fill", SEL_CHAT_MSG, "Здравствуйте") in page.actions


def test_apply_confirms_country_popup_then_sends():
    # Vacancy in another country: hh shows a consent popup before the letter form.
    page = _FakePage({SEL_APPLY: 1, SEL_COUNTRY_CONFIRM: 1,
                      SEL_LETTER_INPUT: 1, SEL_SUBMIT: 1})
    apply_via_page(page, "https://hh.ru/vacancy/3", OutreachContent(body="hi"))
    assert ("click", SEL_COUNTRY_CONFIRM) in page.actions
    assert ("fill", SEL_LETTER_INPUT, "hi") in page.actions
    assert ("click", SEL_SUBMIT) in page.actions


def test_relocation_warning_modal_is_handled():
    """The "You are applying from another country / Still apply" modal
    (relocation-warning-confirm) BLOCKS the letter form; clicking it is what
    unblocked the 6 RU vacancies that reported 'поле письма не появилось'."""
    assert "relocation-warning-confirm" in SEL_COUNTRY_CONFIRM


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
    monkeypatch.setattr(hh, "_verify_submitted", lambda page, debug_dir=None: None)

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
    assert ("jsclick", SEL_CHAT_OPEN_BTN) in page.actions
    assert ("set_input_files", SEL_CHAT_FILE_INPUT, "/cv/me.pdf") in page.actions
    assert ("jsclick", SEL_CHAT_SEND_ENABLED) in page.actions


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

    assert ("jsclick", SEL_CHAT_OPEN_BTN) in page.actions
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


# --- модалка, из-за которой 16 откликов ушли пустыми -------------------------
# Замер 2026-08-23/24: два прогона подряд, 16 откликов на hh — и НИ ОДНОГО
# сопроводительного письма и ни одного CV. Отклик у таких вакансий подаётся в
# один клик (онлайн-резюме), а письмо и файл идут следом через чат вакансии.
# Клик по кнопке чата отваливался по таймауту, и в логе Playwright стояло
# `<div data-qa="modal-overlay"> intercepts pointer events`: сразу после отклика
# hh показывает модалку, и её фон перехватывает клик.
#
# Модалка живёт ровно этот момент — на перезагруженной странице той же вакансии
# (136487691, замер 2026-08-24) модалок ноль, а кнопок чата две и они видимы.
# Кнопки закрытия у неё нет: `[data-qa*=close]` даёт 0.

def test_the_letter_survives_a_modal_that_swallows_the_chat_click():
    """Главная регрессия: письмо обязано дойти, даже когда клик перехвачен."""
    page = _FakePage({SEL_CHAT_OPEN_BTN: 1, SEL_CHAT_MSG: 1, SEL_CHAT_SEND_ENABLED: 1},
                     intercepted={SEL_CHAT_OPEN_BTN})

    attach_cv_via_chat(page, None, None, letter="Здравствуйте")

    assert ("jsclick", SEL_CHAT_OPEN_BTN) in page.actions, "чат не открыли"
    assert ("fill", SEL_CHAT_MSG, "Здравствуйте") in page.actions


def test_the_cv_survives_it_too():
    """CV идёт тем же путём, и в тех же прогонах не дошёл ни разу."""
    page = _FakePage({SEL_CHAT_OPEN_BTN: 1, SEL_CHAT_FILE_INPUT: 1,
                      SEL_CHAT_SEND_ENABLED: 1},
                     intercepted={SEL_CHAT_OPEN_BTN})

    attach_cv_via_chat(page, "/cv/me.pdf", None)

    assert ("set_input_files", SEL_CHAT_FILE_INPUT, "/cv/me.pdf") in page.actions


def test_the_chat_is_opened_without_a_hit_point():
    """Нативный клик, а не клик по координатам: любой оверлей поверх кнопки
    съедает второй. Тот же приём уже применён в канале LinkedIn."""
    page = _FakePage({SEL_CHAT_OPEN_BTN: 1, SEL_CHAT_MSG: 1, SEL_CHAT_SEND_ENABLED: 1})

    attach_cv_via_chat(page, None, None, letter="привет")

    assert ("jsclick", SEL_CHAT_OPEN_BTN) in page.actions
    assert ("click", SEL_CHAT_OPEN_BTN) not in page.actions


def test_a_chat_that_never_opened_is_loud_not_silent():
    """Раньше отсутствие поля сообщения просто пропускало письмо: отклик
    считался успешным, а работодатель не получал ни строчки. Молчать нельзя."""
    import pytest

    page = _FakePage({SEL_CHAT_OPEN_BTN: 1, SEL_CHAT_MSG: 0})

    with pytest.raises(ChannelError, match="поле сообщения"):
        attach_cv_via_chat(page, None, None, letter="Здравствуйте")


# --- чат, в котором писать нельзя, пока не приложишь письмо к отклику --------
# Замер 2026-08-24 на двух реальных чатах одного аккаунта:
#   hh.ru/chat/5569995463 — переписка завязалась, поле сообщения есть;
#   hh.ru/chat/5569971942 — поля нет вовсе, а внизу страницы написано
#   «Chat will be available after the employer sends you an invitation».
# То есть hh НЕ даёт писать работодателю по своей воле: чат открывается только
# после его приглашения. Досылать письмо через переписку в общем случае нельзя.
#
# Но там же hh предлагает своё: «Add a cover letter» — ссылка
# `a[data-qa='chatik-chat-message-applicant-action']` в виджете cover-letter.
# По клику появляются и поле сообщения (тот же `chatik-new-message-text`), и
# поле файла, и кнопка отправки. Это и есть штатный способ приложить письмо к
# уже поданному отклику, и именно он нужен вакансиям с откликом в один клик.

def test_a_chat_without_a_composer_uses_hhs_add_cover_letter_link():
    """Главный случай для откликов в один клик: писать сразу нельзя, но письмо
    к отклику приложить можно."""
    page = _FakePage({SEL_CHAT_OPEN_BTN: 1, SEL_CHAT_MSG: 0, SEL_CHAT_ADD_LETTER: 1})

    attach_cv_via_chat(page, None, None, letter="Здравствуйте")

    assert ("jsclick", SEL_CHAT_ADD_LETTER) in page.actions, "не нажали «Add a cover letter»"
    assert ("fill", SEL_CHAT_MSG, "Здравствуйте") in page.actions


def test_the_cv_rides_the_same_revealed_composer():
    page = _FakePage({SEL_CHAT_OPEN_BTN: 1, SEL_CHAT_MSG: 0, SEL_CHAT_ADD_LETTER: 1,
                      SEL_CHAT_FILE_INPUT: 1})

    attach_cv_via_chat(page, "/cv/me.pdf", None, letter="Здравствуйте")

    assert ("set_input_files", SEL_CHAT_FILE_INPUT, "/cv/me.pdf") in page.actions


def test_an_existing_composer_is_used_as_is():
    """Где переписка уже идёт, ссылки нет — и трогать ничего не нужно."""
    page = _FakePage({SEL_CHAT_OPEN_BTN: 1, SEL_CHAT_MSG: 1, SEL_CHAT_SEND_ENABLED: 1})

    attach_cv_via_chat(page, None, None, letter="привет")

    assert ("jsclick", SEL_CHAT_ADD_LETTER) not in page.actions
    assert ("fill", SEL_CHAT_MSG, "привет") in page.actions


def test_no_composer_and_no_link_still_raises():
    """Ни поля, ни ссылки — писать действительно некуда, и молчать об этом нельзя."""
    import pytest

    page = _FakePage({SEL_CHAT_OPEN_BTN: 1, SEL_CHAT_MSG: 0, SEL_CHAT_ADD_LETTER: 0})

    with pytest.raises(ChannelError, match="поле сообщения"):
        attach_cv_via_chat(page, None, None, letter="Здравствуйте")


def test_in_a_revealed_composer_the_cv_goes_before_the_text_and_both_ride_one_send():
    """Виджет «Add a cover letter» одноразовый: после отправки он исчезает
    вместе с полем файла. Замер 2026-08-24: код приложил письмо, отправил его —
    и на следующем шаге поля файла уже не было, резюме не ушло. Значит файл
    прикладывается ДО текста, а отправка одна."""
    page = _FakePage({SEL_CHAT_OPEN_BTN: 1, SEL_CHAT_MSG: 0, SEL_CHAT_ADD_LETTER: 1,
                      SEL_CHAT_FILE_INPUT: 1})

    attach_cv_via_chat(page, "/cv/me.pdf", None, letter="Здравствуйте")

    kinds = [a for a in page.actions
             if a[0] in ("set_input_files", "fill", "click", "press")
             and a[1] in (SEL_CHAT_FILE_INPUT, SEL_CHAT_MSG, SEL_CHAT_SEND_ENABLED)]
    files = [i for i, a in enumerate(kinds) if a[0] == "set_input_files"]
    fills = [i for i, a in enumerate(kinds) if a[0] == "fill"]
    assert files and fills and files[0] < fills[0], "файл должен идти ДО текста"
    sends = [a for a in page.actions
             if a[:2] in (("jsclick", SEL_CHAT_SEND_ENABLED),)
             or a[:2] == ("press", SEL_CHAT_MSG)]
    assert len(sends) == 1, f"отправка должна быть одна, а их {len(sends)}"


# --- вопросы работодателя: целимся в видимое поле ---------------------------

def test_question_answer_goes_into_the_visible_field(monkeypatch):
    """Лид #461: `fill` простоял 30 с на поле, которое нашлось, но не годилось.

    Сканер вопросов идёт по `document.querySelectorAll` и находит в том числе
    скрытые, а `fill` требует видимое, включённое и редактируемое — поэтому
    видимое поле выбирается явно.
    """
    import app.infrastructure.channels.headhunter as hh

    questions = [{"id": "task_9", "type": "text", "prompt": "p", "options": []}]
    monkeypatch.setattr(hh, "collect_questions", lambda page: questions)
    monkeypatch.setattr(hh, "_verify_submitted", lambda page, debug_dir=None: None)

    page = _FakePage({SEL_APPLY: 1, SEL_QUESTIONS: 1, SEL_LETTER_INPUT: 1,
                      SEL_SUBMIT: 1,
                      "textarea[name='task_9_text']": 2,          # скрытая и видимая
                      "textarea[name='task_9_text']:visible": 1})

    apply_via_page(page, "https://hh.ru/vacancy/1", OutreachContent(body="letter"),
                   lambda qs, vacancy: {"task_9": {"id": "task_9", "text": "ответ"}})

    assert ("fill", "textarea[name='task_9_text']:visible", "ответ") in page.actions
    assert ("fill", "textarea[name='task_9_text']", "ответ") not in page.actions


def test_question_answer_falls_back_when_nothing_is_visible(monkeypatch):
    """Видимых нет — причина другая, и её надо увидеть, а не замаскировать."""
    import app.infrastructure.channels.headhunter as hh

    questions = [{"id": "task_9", "type": "text", "prompt": "p", "options": []}]
    monkeypatch.setattr(hh, "collect_questions", lambda page: questions)
    monkeypatch.setattr(hh, "_verify_submitted", lambda page, debug_dir=None: None)

    page = _FakePage({SEL_APPLY: 1, SEL_QUESTIONS: 1, SEL_LETTER_INPUT: 1,
                      SEL_SUBMIT: 1, "textarea[name='task_9_text']": 1})

    apply_via_page(page, "https://hh.ru/vacancy/1", OutreachContent(body="letter"),
                   lambda qs, vacancy: {"task_9": {"id": "task_9", "text": "ответ"}})

    assert ("fill", "textarea[name='task_9_text']", "ответ") in page.actions


def test_failed_question_saves_the_page_before_giving_up(monkeypatch, tmp_path):
    """Без снимка «Timeout 30000ms» не отвечает, ПОЧЕМУ поле не приняло ответ."""
    import app.infrastructure.channels.headhunter as hh

    questions = [{"id": "task_9", "type": "text", "prompt": "p", "options": []}]
    monkeypatch.setattr(hh, "collect_questions", lambda page: questions)

    dumped = []
    monkeypatch.setattr(hh, "_dump_chat_debug",
                        lambda page, d, tag: dumped.append((d, tag)))

    def boom(page, qid, value):
        raise TimeoutError("Locator.fill: Timeout 30000ms exceeded")

    monkeypatch.setattr(hh, "_fill_text_answer", boom)

    page = _FakePage({SEL_APPLY: 1, SEL_QUESTIONS: 1, SEL_LETTER_INPUT: 1, SEL_SUBMIT: 1})

    with pytest.raises(TimeoutError):
        apply_via_page(page, "https://hh.ru/vacancy/1", OutreachContent(body="l"),
                       lambda qs, v: {"task_9": {"id": "task_9", "text": "a"}},
                       debug_dir=str(tmp_path))

    assert dumped == [(str(tmp_path), "hh_question_text_task_9")]


def test_rejected_form_saves_the_page_before_giving_up(monkeypatch, tmp_path):
    """Лид #466: «форма не принята» — причину форма пишет на себе, не в ошибке."""
    import app.infrastructure.channels.headhunter as hh

    dumped = []
    monkeypatch.setattr(hh, "_dump_chat_debug",
                        lambda page, d, tag: dumped.append((d, tag)))

    page = _FakePage({SEL_APPLY: 1, SEL_LETTER_TOGGLE: 1, SEL_LETTER_INPUT: 1,
                      SEL_SUBMIT: 1}, submit_sticks=True)

    with pytest.raises(ChannelError, match="не подтверждён"):
        apply_via_page(page, "https://hh.ru/vacancy/1", OutreachContent(body="hi"),
                       debug_dir=str(tmp_path))

    assert dumped == [(str(tmp_path), "hh_form_rejected")]


# --- отклик прошёл, а мы объявляли неудачу -----------------------------------
#
# Замер 2026-09-01/02: лиды #733 (vacancy/135035753) и #738 (136597256) упали с
# «поле письма не появилось и отклик не подтверждён». В сохранённом дампе стояла
# кнопка отклика и НЕ было отметки «вы откликались». На следующий день hh на обе
# вакансии ответил «already applied» — заявки тогда УШЛИ. Сообщение врало в
# самую опасную сторону: человек считает, что не откликнулся, и идёт снова.
#
# Причина: hh не перерисовывает страницу после отклика, отметка появляется
# только на свежей загрузке.

class _ReloadPage(_FakePage):
    """Страница, которая показывает отметку об отклике только после goto."""

    def __init__(self, counts, applied_after_reload=True):
        super().__init__(counts)
        self._gotos = 0
        self._applies = applied_after_reload

    def goto(self, url, **kw):
        super().goto(url, **kw)
        self._gotos += 1
        # Отметка появляется со ВТОРОГО захода: первый — это открытие вакансии
        # в начале отклика, и на нём её ещё нет, иначе сработал бы верхний
        # страж «already applied» и до письма дело бы не дошло.
        if self._applies and self._gotos >= 2:
            self._counts[SEL_ALREADY_APPLIED] = 1

    def inner_text(self, selector):
        return ""


def test_a_letterless_apply_is_rechecked_before_being_called_a_failure():
    page = _ReloadPage({SEL_APPLY: 1, SEL_LETTER_TOGGLE: 1, SEL_LETTER_INPUT: 0,
                        SEL_ALREADY_APPLIED: 0})
    apply_via_page(page, "https://hh.ru/vacancy/135035753",
                   OutreachContent(body="Здравствуйте"))

    # Перезагрузка была, и вердикт «не отправлено» не прозвучал.
    assert ("goto", "https://hh.ru/vacancy/135035753") in page.actions


def test_a_genuinely_unsent_application_still_fails_loudly():
    """Перезагрузка не должна превращать настоящую неудачу в тихий успех."""
    page = _ReloadPage({SEL_APPLY: 1, SEL_LETTER_TOGGLE: 1, SEL_LETTER_INPUT: 0,
                        SEL_ALREADY_APPLIED: 0}, applied_after_reload=False)

    with pytest.raises(ChannelError, match="даже после перезагрузки"):
        apply_via_page(page, "https://hh.ru/vacancy/1", OutreachContent(body="hi"))


def test_the_recheck_costs_nothing_when_the_letter_field_is_there():
    """Лишняя загрузка только на пути к неудаче, а не на каждом отклике."""
    page = _ReloadPage({SEL_APPLY: 1, SEL_LETTER_TOGGLE: 1,
                        SEL_LETTER_INPUT: 1, SEL_SUBMIT: 1})
    apply_via_page(page, "https://hh.ru/vacancy/2", OutreachContent(body="hi"))

    assert [a for a in page.actions if a[0] == "goto"] == [
        ("goto", "https://hh.ru/vacancy/2")]        # только первый заход
