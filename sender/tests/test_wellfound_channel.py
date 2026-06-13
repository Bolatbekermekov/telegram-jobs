import pytest

from app.domain.channel import ChannelError, OutreachContent
from app.infrastructure.channels.wellfound import apply_via_page


class _FakePage:
    def __init__(self, has_apply=True):
        self.actions = []
        self._has_apply = has_apply

    def goto(self, url, **kw):
        self.actions.append(("goto", url))

    def get_by_role(self, role, name=None):
        page = self
        class _Locator:
            def count(self_inner):
                return 1 if (name != "Apply" or page._has_apply) else 0
            def first(self_inner): return self_inner
            def click(self_inner): page.actions.append(("click", name))
        return _Locator()

    def get_by_placeholder(self, text):
        page = self
        class _Box:
            def fill(self_inner, value): page.actions.append(("fill", value))
        return _Box()


def test_apply_fills_message_and_submits():
    page = _FakePage(has_apply=True)
    apply_via_page(page, "https://wellfound.com/jobs/123", OutreachContent(body="Hi team"))
    assert ("goto", "https://wellfound.com/jobs/123") in page.actions
    assert ("click", "Apply") in page.actions
    assert ("fill", "Hi team") in page.actions
    assert ("click", "Submit application") in page.actions


def test_apply_raises_without_apply_button():
    page = _FakePage(has_apply=False)
    with pytest.raises(ChannelError):
        apply_via_page(page, "https://wellfound.com/jobs/1", OutreachContent(body="Hi"))
