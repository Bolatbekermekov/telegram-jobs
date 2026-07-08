import pytest

from app.domain.channel import ChannelError, OutreachContent, RateLimitedError
from app.infrastructure.channels.headhunter import (
    SEL_ALREADY_APPLIED,
    SEL_APPLY,
    SEL_LETTER_INPUT,
    SEL_LETTER_TOGGLE,
    SEL_COUNTRY_CONFIRM,
    SEL_QUESTIONS,
    SEL_SUBMIT,
    HeadHunterChannel,
    apply_via_page,
    extract_vacancy_id,
    vacancy_url,
)


class _FakePage:
    """Maps selector -> element count; records goto/click/fill actions.

    Clicking the submit button removes it (models a successful send) unless
    submit_sticks=True (models a rejected form).
    """

    def __init__(self, counts, url="https://hh.ru/vacancy/1", submit_sticks=False):
        self._counts = counts
        self.url = url
        self.actions = []
        self._submitted = False
        self._submit_sticks = submit_sticks

    def goto(self, url, **kw):
        self.actions.append(("goto", url))

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

            def nth(self_inner, i):
                return self_inner

            def click(self_inner):
                if selector == SEL_SUBMIT:
                    page._submitted = True
                page.actions.append(("click", selector))

            def fill(self_inner, value):
                page.actions.append(("fill", selector, value))

            def check(self_inner):
                page.actions.append(("check", selector))

        return _Locator()

    def wait_for_selector(self, selector, **kw):
        self.actions.append(("wait", selector))

    def wait_for_timeout(self, ms):
        pass


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
    assert ("wait", f"{SEL_COUNTRY_CONFIRM}, {SEL_LETTER_TOGGLE}, {SEL_LETTER_INPUT}") \
        in page.actions


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
    with pytest.raises(ChannelError, match="no apply button"):
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
