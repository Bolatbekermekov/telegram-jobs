import pytest

from app.domain.channel import ChannelError, OutreachContent, RateLimitedError
from app.infrastructure.channels.headhunter import (
    SEL_ALREADY_APPLIED,
    SEL_APPLY,
    SEL_LETTER_INPUT,
    SEL_LETTER_TOGGLE,
    SEL_RELOCATION_CONFIRM,
    SEL_SUBMIT,
    HeadHunterChannel,
    apply_via_page,
    extract_vacancy_id,
    vacancy_url,
)


class _FakePage:
    """Maps selector -> element count; records goto/click/fill actions."""

    def __init__(self, counts, url="https://hh.ru/vacancy/1"):
        self._counts = counts
        self.url = url
        self.actions = []

    def goto(self, url, **kw):
        self.actions.append(("goto", url))

    def locator(self, selector):
        page = self

        class _Locator:
            def count(self_inner):
                return page._counts.get(selector, 0)

            @property
            def first(self_inner):
                return self_inner

            def click(self_inner):
                page.actions.append(("click", selector))

            def fill(self_inner, value):
                page.actions.append(("fill", selector, value))

        return _Locator()

    def wait_for_selector(self, selector, **kw):
        self.actions.append(("wait", selector))


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
    assert ("wait", f"{SEL_LETTER_INPUT}, {SEL_RELOCATION_CONFIRM}") in page.actions


def test_apply_without_letter_toggle_fills_directly():
    # Some vacancies show the letter textarea right away (no toggle).
    page = _FakePage({SEL_APPLY: 1, SEL_LETTER_INPUT: 1, SEL_SUBMIT: 1})
    apply_via_page(page, "https://hh.ru/vacancy/2", OutreachContent(body="hi"))
    assert ("fill", SEL_LETTER_INPUT, "hi") in page.actions
    assert ("click", SEL_SUBMIT) in page.actions


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


def test_channel_metadata():
    ch = HeadHunterChannel("hh.json", True)
    assert ch.name == "hh"
    assert ch.body_limit == 10000
    assert ch.needs_subject is False
