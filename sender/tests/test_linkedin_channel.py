import pytest

from app.domain.channel import ChannelError, OutreachContent
from app.infrastructure.channels.linkedin import fill_and_send


class _FakePage:
    def __init__(self, message_button=True):
        self.actions = []
        self._has_message = message_button
        self.keyboard = _FakeKeyboard(self)

    def goto(self, url, **kw):
        self.actions.append(("goto", url))

    def get_by_role(self, role, name=None):
        self.actions.append(("get_by_role", role, name))
        page = self
        class _Locator:
            def count(self_inner):
                if name == "Message":
                    return 1 if page._has_message else 0
                return 1
            @property
            def first(self_inner): return self_inner
            def click(self_inner): page.actions.append(("click", name))
        return _Locator()

    def get_by_label(self, label, **kw):
        page = self
        class _Box:
            def fill(self_inner, text): page.actions.append(("fill", label, text))
        return _Box()


class _FakeKeyboard:
    def __init__(self, page):
        self._page = page

    def press(self, key):
        self._page.actions.append(("press", key))


def test_fill_and_send_messages_connection():
    page = _FakePage(message_button=True)
    fill_and_send(page, "https://linkedin.com/in/someone",
                  OutreachContent(body="Hi there"))
    assert ("goto", "https://linkedin.com/in/someone") in page.actions
    assert ("click", "Message") in page.actions
    assert any(a[0] == "fill" and a[2] == "Hi there" for a in page.actions)


def test_fill_and_send_raises_without_message_button():
    page = _FakePage(message_button=False)
    with pytest.raises(ChannelError):
        fill_and_send(page, "https://linkedin.com/in/x", OutreachContent(body="Hi"))


from app.infrastructure.channels.linkedin import (
    SEL_APPLY_SUBMIT,
    SEL_EASY_APPLY,
    easy_apply_via_page,
    LinkedInChannel,
)


class _FakeApplyPage:
    """Maps selector -> element count; records goto/click actions."""

    def __init__(self, counts):
        self._counts = counts
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

        return _Locator()


def test_easy_apply_single_step_submits():
    page = _FakeApplyPage({SEL_EASY_APPLY: 1, SEL_APPLY_SUBMIT: 1})
    easy_apply_via_page(page, "https://www.linkedin.com/jobs/view/9",
                        OutreachContent(body="hi"))
    assert ("goto", "https://www.linkedin.com/jobs/view/9") in page.actions
    assert ("click", SEL_EASY_APPLY) in page.actions
    assert ("click", SEL_APPLY_SUBMIT) in page.actions


def test_easy_apply_external_job_skipped():
    # No jobs-apply-button = external apply -> skip with a clear reason.
    page = _FakeApplyPage({})
    with pytest.raises(ChannelError, match="внешний отклик"):
        easy_apply_via_page(page, "https://www.linkedin.com/jobs/view/1",
                            OutreachContent(body="hi"))


def test_easy_apply_multistep_skipped():
    # Easy Apply present but no immediate submit = multi-step form -> skip.
    page = _FakeApplyPage({SEL_EASY_APPLY: 1})
    with pytest.raises(ChannelError, match="многошаговый"):
        easy_apply_via_page(page, "https://www.linkedin.com/jobs/view/2",
                            OutreachContent(body="hi"))


def test_send_routes_job_url_to_easy_apply(monkeypatch):
    called = {}
    monkeypatch.setattr("app.infrastructure.channels.linkedin.easy_apply_via_page",
                        lambda page, url, content: called.setdefault("easy", url))
    monkeypatch.setattr("app.infrastructure.channels.linkedin.fill_and_send",
                        lambda page, url, content: called.setdefault("dm", url))
    ch = LinkedInChannel("state.json")
    ch._page = object()
    ch.send("https://www.linkedin.com/jobs/view/9", OutreachContent(body="hi"))
    assert called == {"easy": "https://www.linkedin.com/jobs/view/9"}


def test_send_routes_profile_url_to_dm(monkeypatch):
    called = {}
    monkeypatch.setattr("app.infrastructure.channels.linkedin.easy_apply_via_page",
                        lambda page, url, content: called.setdefault("easy", url))
    monkeypatch.setattr("app.infrastructure.channels.linkedin.fill_and_send",
                        lambda page, url, content: called.setdefault("dm", url))
    ch = LinkedInChannel("state.json")
    ch._page = object()
    ch.send("https://www.linkedin.com/in/jane", OutreachContent(body="hi"))
    assert called == {"dm": "https://www.linkedin.com/in/jane"}
