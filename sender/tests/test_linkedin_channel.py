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


from app.infrastructure.channels.linkedin import easy_apply_via_page, LinkedInChannel


class _FakeLocator:
    def __init__(self, count=1):
        self._count = count
        self.clicked = False
        self.filled = None
        self.first = self

    def count(self):
        return self._count

    def click(self):
        self.clicked = True

    def fill(self, text):
        self.filled = text


class _FakeApplyPage:
    def __init__(self):
        self.goto_url = None
        self._apply = _FakeLocator()
        self._note = _FakeLocator()
        self._submit = _FakeLocator()

    def goto(self, url, wait_until=None):
        self.goto_url = url

    def get_by_role(self, role, name=None):
        if name == "Easy Apply":
            return self._apply
        if name and "Submit" in name:
            return self._submit
        return _FakeLocator(count=0)

    def get_by_label(self, label):
        return self._note


def test_easy_apply_fills_and_submits():
    page = _FakeApplyPage()
    easy_apply_via_page(page, "https://www.linkedin.com/jobs/view/9",
                        OutreachContent(body="hi"))
    assert page.goto_url == "https://www.linkedin.com/jobs/view/9"
    assert page._apply.clicked and page._submit.clicked


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
