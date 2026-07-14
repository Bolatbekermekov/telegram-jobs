import pytest

from app.domain.channel import ChannelError, InvitePendingError, OutreachContent
from app.infrastructure.channels.linkedin import (
    SEL_CONNECT_BTN,
    SEL_FILE_INPUT,
    SEL_INVITE_SEND,
    SEL_MESSAGE_BTN,
    SEL_MSG_BOX,
    SEL_MSG_SEND,
    SEL_NOTE_BOX,
    SEL_PERSONALIZE,
    connect_with_note,
    fill_and_send,
    message_or_connect,
)


class _FakePage:
    """Maps selector -> element count; records goto/click/fill/upload actions."""

    def __init__(self, counts=None):
        self.actions = []
        self._counts = counts or {}
        self.keyboard = _FakeKeyboard(self)

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

            @property
            def last(self_inner):
                return self_inner

            def click(self_inner):
                page.actions.append(("click", selector))

            def fill(self_inner, text):
                page.actions.append(("fill", selector, text))

            def set_input_files(self_inner, p):
                page.actions.append(("set_input_files", selector, p))

            def dispatch_event(self_inner, ev):
                page.actions.append(("dispatch", selector, ev))

            def scroll_into_view_if_needed(self_inner):
                pass

        return _Locator()

    def wait_for_timeout(self, ms):
        pass


class _FakeKeyboard:
    def __init__(self, page):
        self._page = page

    def press(self, key):
        self._page.actions.append(("press", key))


# A messageable profile: message button, compose box, and enabled send.
_MSG_OK = {SEL_MESSAGE_BTN: 1, SEL_MSG_BOX: 1, SEL_MSG_SEND: 1}


def test_fill_and_send_messages_connection():
    page = _FakePage(dict(_MSG_OK))
    fill_and_send(page, "https://linkedin.com/in/someone", OutreachContent(body="Hi there"))
    assert ("goto", "https://linkedin.com/in/someone") in page.actions
    assert ("click", SEL_MESSAGE_BTN) in page.actions
    assert ("fill", SEL_MSG_BOX, "Hi there") in page.actions
    assert ("click", SEL_MSG_SEND) in page.actions


def test_fill_and_send_raises_without_message_button():
    page = _FakePage({})
    with pytest.raises(ChannelError, match="Сообщение"):
        fill_and_send(page, "https://linkedin.com/in/x", OutreachContent(body="Hi"))


def test_fill_and_send_attaches_cv_when_present():
    page = _FakePage({**_MSG_OK, SEL_FILE_INPUT: 1})
    fill_and_send(page, "https://linkedin.com/in/someone",
                  OutreachContent(body="Hi", attachment_path="/cv/me.pdf"))
    assert ("set_input_files", SEL_FILE_INPUT, "/cv/me.pdf") in page.actions


def test_fill_and_send_fails_loud_when_no_file_input():
    # Attachment requested but composer has no file input -> don't send CV-less.
    page = _FakePage(dict(_MSG_OK))
    with pytest.raises(ChannelError, match="вложения"):
        fill_and_send(page, "https://linkedin.com/in/someone",
                      OutreachContent(body="Hi", attachment_path="/cv/me.pdf"))


def test_fill_and_send_no_attachment_skips_upload():
    page = _FakePage(dict(_MSG_OK))
    fill_and_send(page, "https://linkedin.com/in/someone", OutreachContent(body="Hi"))
    assert not any(a[0] == "set_input_files" for a in page.actions)


def test_message_or_connect_messages_when_possible():
    page = _FakePage(dict(_MSG_OK))
    message_or_connect(page, "https://linkedin.com/in/a", OutreachContent(body="Hi"))
    assert ("click", SEL_MESSAGE_BTN) in page.actions


# A profile where we can't message, but the connect+note flow works.
_CONNECT_OK = {SEL_CONNECT_BTN: 1, SEL_PERSONALIZE: 1, SEL_NOTE_BOX: 1, SEL_INVITE_SEND: 1}


def test_connect_with_note_sends_invite():
    page = _FakePage(dict(_CONNECT_OK))
    connect_with_note(page, "Здравствуйте, интересна ваша вакансия QA")
    assert ("dispatch", SEL_CONNECT_BTN, "click") in page.actions   # overlay-proof click
    assert ("click", SEL_PERSONALIZE) in page.actions
    assert any(a[0] == "fill" and a[1] == SEL_NOTE_BOX for a in page.actions)
    assert ("click", SEL_INVITE_SEND) in page.actions


def test_connect_with_note_truncates_note_to_limit():
    page = _FakePage(dict(_CONNECT_OK))
    connect_with_note(page, "x" * 500)
    note = next(a[2] for a in page.actions if a[0] == "fill" and a[1] == SEL_NOTE_BOX)
    assert len(note) == 200


def test_connect_with_note_raises_when_modal_missing():
    page = _FakePage({SEL_CONNECT_BTN: 1})  # connect clicks but no personalize modal
    with pytest.raises(ChannelError, match="приглашения"):
        connect_with_note(page, "hi")


def test_message_or_connect_sends_invite_when_only_connect():
    # Can't message, only connect -> invite with note, signalled InvitePendingError.
    page = _FakePage(dict(_CONNECT_OK))
    with pytest.raises(InvitePendingError):
        message_or_connect(page, "https://linkedin.com/in/a", OutreachContent(body="Hi"))
    assert ("click", SEL_INVITE_SEND) in page.actions


def test_message_or_connect_raises_when_no_action():
    page = _FakePage({})
    with pytest.raises(ChannelError, match="не найдены"):
        message_or_connect(page, "https://linkedin.com/in/a", OutreachContent(body="Hi"))


from app.infrastructure.channels.linkedin import (
    SEL_APPLY_SUBMIT,
    SEL_EASY_APPLY,
    easy_apply_via_page,
    LinkedInChannel,
    _ExternalApplyNeeded,
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


def test_easy_apply_external_job_signals_handoff():
    # No jobs-apply-button = external apply -> signal hand-off; the channel then
    # runs the external-apply driver instead of erroring here.
    page = _FakeApplyPage({})
    with pytest.raises(_ExternalApplyNeeded):
        easy_apply_via_page(page, "https://www.linkedin.com/jobs/view/1",
                            OutreachContent(body="hi"))


def test_easy_apply_multistep_skipped():
    # Easy Apply present but no immediate submit = multi-step form -> skip.
    page = _FakeApplyPage({SEL_EASY_APPLY: 1})
    with pytest.raises(ChannelError, match="многошаговый"):
        easy_apply_via_page(page, "https://www.linkedin.com/jobs/view/2",
                            OutreachContent(body="hi"))


def _patch_routes(monkeypatch):
    called = {}
    monkeypatch.setattr("app.infrastructure.channels.linkedin.easy_apply_via_page",
                        lambda page, url, content: called.setdefault("easy", url))
    monkeypatch.setattr("app.infrastructure.channels.linkedin.message_or_connect",
                        lambda page, url, content: called.setdefault("msg", url))
    return called


def test_send_routes_job_url_to_easy_apply(monkeypatch):
    called = _patch_routes(monkeypatch)
    ch = LinkedInChannel("state.json")
    ch._page = object()
    ch.send("https://www.linkedin.com/jobs/view/9", OutreachContent(body="hi"))
    assert called == {"easy": "https://www.linkedin.com/jobs/view/9"}


def test_send_routes_profile_url_to_message(monkeypatch):
    called = _patch_routes(monkeypatch)
    ch = LinkedInChannel("state.json")
    ch._page = object()
    ch.send("https://www.linkedin.com/in/jane", OutreachContent(body="hi"))
    assert called == {"msg": "https://www.linkedin.com/in/jane"}


def test_send_routes_post_url_to_author_message(monkeypatch):
    # A post URL -> message the AUTHOR resolved from the post slug.
    called = _patch_routes(monkeypatch)
    ch = LinkedInChannel("state.json")
    ch._page = object()
    ch.send("https://www.linkedin.com/posts/ilyas-mustafin-44b575144_x-activity-7-CmC7/",
            OutreachContent(body="hi"))
    assert called == {"msg": "https://www.linkedin.com/in/ilyas-mustafin-44b575144/"}
