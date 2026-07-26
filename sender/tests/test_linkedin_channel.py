import json

import pytest

from app.domain.channel import (
    ChannelError, ChannelUnavailable, InvitePendingError, OutreachContent,
    RateLimitedError,
)
from app.infrastructure.channels import linkedin as _li
from app.infrastructure.channels.linkedin import (
    SEL_FILE_INPUT,
    SEL_INVITE_SEND,
    SEL_MENU_CONNECT,
    SEL_MESSAGE_BTN,
    SEL_MORE_BTN,
    SEL_MSG_BOX,
    SEL_MSG_SEND,
    SEL_NOTE_BOX,
    SEL_PERSONALIZE,
    LinkedInChannel,
    connect_with_note,
    fill_and_send,
    message_or_connect,
)


def test_start_rejects_a_logged_out_session(tmp_path):
    """A state file with no `li_at` must stop the run (re-login), not start a
    guest browser that fails every profile at the authwall — the row-79 bug."""
    dead = tmp_path / "linkedin_state.json"
    dead.write_text(json.dumps({"cookies": [{"name": "bcookie", "value": "v=2"}]}))
    with pytest.raises(ChannelUnavailable):
        LinkedInChannel(str(dead)).start()


def test_start_rejects_a_missing_session(tmp_path):
    with pytest.raises(ChannelUnavailable):
        LinkedInChannel(str(tmp_path / "nope.json")).start()


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

            def evaluate(self_inner, expr, timeout=None):
                # _click_via_dom uses locator.evaluate("el => el.click()", timeout=…)
                page.actions.append(("jsclick", selector))

            def wait_for(self_inner, state=None, timeout=None):
                # Model Playwright: a present element resolves, an absent one
                # times out (raises) — that's how _visible() reads readiness.
                if page._counts.get(selector, 0) == 0:
                    raise TimeoutError(f"wait_for timeout: {selector}")

            def scroll_into_view_if_needed(self_inner):
                pass

        return _Locator()

    def wait_for_timeout(self, ms):
        pass

    def wait_for_load_state(self, state, timeout=None):
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
    assert ("jsclick", SEL_MESSAGE_BTN) in page.actions
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


def test_message_or_connect_messages_a_first_degree_contact():
    # 1st-degree: no Connect action anywhere -> free message. The button is
    # opened with a native in-page click to clear LinkedIn's sticky nav layer.
    page = _FakePage(dict(_MSG_OK))
    message_or_connect(page, "https://linkedin.com/in/a", OutreachContent(body="Hi"))
    assert ("jsclick", SEL_MESSAGE_BTN) in page.actions
    assert ("fill", SEL_MSG_BOX, "Hi") in page.actions


# A non-contact reached through the "…"/Еше menu (the only Connect path).
_CONNECT_OK = {SEL_MORE_BTN: 1, SEL_MENU_CONNECT: 1,
               SEL_PERSONALIZE: 1, SEL_NOTE_BOX: 1, SEL_INVITE_SEND: 1}


def test_connect_with_note_sends_invite():
    page = _FakePage(dict(_CONNECT_OK))
    connect_with_note(page, "Здравствуйте, интересна ваша вакансия QA")
    assert ("jsclick", SEL_MORE_BTN) in page.actions       # opened the … menu
    assert ("jsclick", SEL_MENU_CONNECT) in page.actions   # native-click, overlay-proof
    assert ("click", SEL_PERSONALIZE) in page.actions
    assert any(a[0] == "fill" and a[1] == SEL_NOTE_BOX for a in page.actions)
    assert ("click", SEL_INVITE_SEND) in page.actions


def test_connect_with_note_truncates_note_to_limit():
    page = _FakePage(dict(_CONNECT_OK))
    connect_with_note(page, "x" * 500)
    note = next(a[2] for a in page.actions if a[0] == "fill" and a[1] == SEL_NOTE_BOX)
    assert len(note) == 200


def test_connect_with_note_raises_when_modal_missing():
    # Menu opens with a Connect entry, but clicking it never surfaces the note
    # modal — a real failure, not a silent skip.
    page = _FakePage({SEL_MORE_BTN: 1, SEL_MENU_CONNECT: 1})
    with pytest.raises(ChannelError, match="приглашения"):
        connect_with_note(page, "hi")


def test_invite_limit_stops_the_platform():
    """Monthly personalized-invite quota spent: "Персонализировать" shows a Premium
    upsell, no note field. Raise RateLimitedError so the run stops LinkedIn
    connects (leads stay `new`) instead of sending note-less invites."""
    from app.infrastructure.channels.linkedin import SEL_INVITE_LIMIT
    page = _FakePage({SEL_MORE_BTN: 1, SEL_MENU_CONNECT: 1,
                      SEL_PERSONALIZE: 1, SEL_INVITE_LIMIT: 1})  # note box absent
    with pytest.raises(RateLimitedError, match="лимит"):
        message_or_connect(page, "https://linkedin.com/in/x", OutreachContent(body="Hi"))


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


# A 3rd-degree profile (Daria, row 79): messaging is InMail-only (Premium), and
# Connect lives under the "Еще" overflow menu, not the top card.
_THIRD_DEGREE = {SEL_MESSAGE_BTN: 1, SEL_MORE_BTN: 1, SEL_MENU_CONNECT: 1,
                 SEL_PERSONALIZE: 1, SEL_NOTE_BOX: 1, SEL_INVITE_SEND: 1}


def test_message_or_connect_connects_when_message_is_inmail_only():
    """Row-79 fix: don't message a non-contact into the InMail paywall — connect.

    The Connect action is reached through the "Еще" menu, and the outcome is a
    pending invite, not a delivered message."""
    page = _FakePage(dict(_THIRD_DEGREE))
    with pytest.raises(InvitePendingError):
        message_or_connect(page, "https://linkedin.com/in/daria", OutreachContent(body="Hi"))
    assert ("jsclick", SEL_MORE_BTN) in page.actions      # opened the … menu
    assert ("jsclick", SEL_MENU_CONNECT) in page.actions  # picked Connect
    assert ("click", SEL_INVITE_SEND) in page.actions               # invite sent
    # Never fell through to the InMail message composer.
    assert not any(a[0] == "fill" and a[1] == SEL_MSG_BOX for a in page.actions)


def test_message_or_connect_connects_a_second_degree_via_top_card(monkeypatch):
    """2nd-degree (a hiring post's author, e.g. rodion-kozlov): Connect is a
    primary top-card control, not in the menu. Use it — don't fall through to the
    InMail paywall. _topcard_connect anchors it past the recommendation cards."""
    page = _FakePage({SEL_PERSONALIZE: 1, SEL_NOTE_BOX: 1, SEL_INVITE_SEND: 1})
    monkeypatch.setattr(_li, "_topcard_connect", lambda p: p.locator("TOPCARD_CONNECT"))
    with pytest.raises(InvitePendingError):
        message_or_connect(page, "https://linkedin.com/in/rodion", OutreachContent(body="Hi"))
    assert ("jsclick", "TOPCARD_CONNECT") in page.actions   # clicked the top-card Connect
    assert ("click", SEL_INVITE_SEND) in page.actions       # invite sent
    assert not any(a[0] == "jsclick" and a[1] == SEL_MORE_BTN for a in page.actions)  # menu not used


def test_message_or_connect_prefers_connect_over_message():
    """When both a top-level Connect and a Message button exist (2nd-degree),
    connect+note wins — a free invite beats a paid InMail."""
    page = _FakePage({SEL_MESSAGE_BTN: 1, SEL_MSG_BOX: 1, **_CONNECT_OK})
    with pytest.raises(InvitePendingError):
        message_or_connect(page, "https://linkedin.com/in/b", OutreachContent(body="Hi"))
    assert not any(a[0] == "fill" and a[1] == SEL_MSG_BOX for a in page.actions)


def test_message_raises_manual_when_only_inmail(monkeypatch):
    """A non-contact with no Connect anywhere (InMail-only, no invite path) must
    be flagged for a manual apply, not sent a message into a composer that never
    opens."""
    from app.domain.channel import ManualApplyRequired
    page = _FakePage({SEL_MESSAGE_BTN: 1})   # message button exists, but no msg box
    with pytest.raises(ManualApplyRequired):
        message_or_connect(page, "https://linkedin.com/in/c", OutreachContent(body="Hi"))


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
