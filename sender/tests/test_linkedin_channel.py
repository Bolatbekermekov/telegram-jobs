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
