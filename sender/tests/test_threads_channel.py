"""ThreadsChannel is the DM fallback: used only when the thread carried no contact."""
import pytest

from app.domain.channel import (
    ChannelError,
    ChannelUnavailable,
    ManualApplyRequired,
    OutreachContent,
)
from app.infrastructure.channels.threads import ThreadsChannel, normalize_target


def test_class_attrs_satisfy_the_protocol():
    from app.domain.channel import OutreachChannel
    ch = ThreadsChannel("threads_state.json", True)
    assert isinstance(ch, OutreachChannel)
    assert ch.name == "threads"
    assert ch.needs_subject is False
    assert isinstance(ch.body_limit, int)


def test_normalize_target():
    assert normalize_target("@skyluckwalker") == "skyluckwalker"
    assert normalize_target("skyluckwalker") == "skyluckwalker"
    assert normalize_target("https://www.threads.com/@skyluckwalker") == "skyluckwalker"
    assert normalize_target("  @Sky_1  ") == "Sky_1"


def test_normalize_target_digs_the_handle_out_of_any_threads_url():
    """Источник is hand-editable, so it is not always the canonical form. A post
    URL, the mobile host and a URL sitting inside a sentence all name one author."""
    assert normalize_target("https://m.threads.com/@hr_acme/post/DbL4LxBl6v9") == "hr_acme"
    assert normalize_target("https://www.threads.net/@hr_acme") == "hr_acme"
    assert normalize_target("threads.com/@hr.acme") == "hr.acme"
    assert normalize_target("пиши автору https://www.threads.com/@hr_acme") == "hr_acme"


def test_normalize_target_refuses_what_is_not_a_handle():
    """Not cosmetic. Today every target dead-ends at ManualApplyRequired, so nothing
    can be mis-sent — but the moment _deliver is implemented, whatever comes out of
    here is typed into the DM composer as a username. So anything that is not one
    handle must resolve to "", the existing "I can't tell who to write to" signal
    that send() turns into a ChannelError.

    The limit of the guard, stated so the next reader does not over-trust it: the
    shape check runs on the WHOLE string and only when no Threads URL matched. Two
    BARE handles are therefore refused (that string never matches the URL pattern,
    so it has to pass the whole-string check) — but two URLs are NOT: the first one
    wins, pinned in the test below."""
    for junk in ["", "   ", "спросить у Пети", "https://example.com/@nick",
                 "https://notthreads.com/@nick", "@nick, а не ответит — пиши @other",
                 "@" + "n" * 31]:
        assert normalize_target(junk) == "", junk


def test_normalize_target_takes_the_first_of_two_threads_urls():
    """The documented limit of the guard above, pinned rather than left to chance.
    A cell naming two different people resolves to the first, silently — the URL
    branch returns before any whole-string check can object. Harmless while the
    composer is unimplemented; whoever writes `_deliver` should know this is a
    first-wins rule and not mistake it for a refusal."""
    two = "https://www.threads.com/@hr_acme и https://www.threads.com/@other"
    assert normalize_target(two) == "hr_acme"


def test_an_unparseable_target_is_a_channel_error_not_a_send():
    """It must never reach _deliver: a lead nobody can be identified from is a
    broken row, and the run says so instead of DMing something shaped like prose."""
    ch = ThreadsChannel("s.json", True)
    ch._deliver = lambda handle, body: pytest.fail("_deliver must not be reached")
    with pytest.raises(ChannelError):
        ch.send("спросить у Пети", OutreachContent(body="Привет"))


def test_start_without_a_live_session_is_channel_unavailable(tmp_path, monkeypatch):
    """A dead burner session must stop cleanly with a re-login hint, not fail the
    lead: the lead was never attempted."""
    import app.infrastructure.channels.threads as mod
    monkeypatch.setattr(mod, "has_valid_session", lambda p: False)
    with pytest.raises(ChannelUnavailable) as exc:
        ThreadsChannel(str(tmp_path / "s.json"), True).start()
    assert "login_threads" in str(exc.value)


def test_attachment_is_ignored_not_an_error():
    """Threads DMs carry text/photo/video/GIF/sticker only — no documents. A CV
    path must be silently dropped, never crash the send."""
    ch = ThreadsChannel("s.json", True)
    sent = {}
    ch._deliver = lambda handle, body: sent.update(handle=handle, body=body)
    ch.send("@sky", OutreachContent(body="Привет", attachment_path="/cv/me.pdf"))
    assert sent == {"handle": "sky", "body": "Привет"}


def test_the_unpinned_composer_is_a_manual_apply():
    """The DM composer's selectors are not pinned yet — they cannot be read without
    a logged-in account, and this project pins selectors from the live page rather
    than guessing them. That account does not exist yet, so this is still true at
    the end of the feature: reaching the composer must raise the project's own
    "couldn't be automated" signal, never a bare crash."""
    ch = ThreadsChannel("s.json", True)
    with pytest.raises(ManualApplyRequired) as exc:
        ch.send("@sky", OutreachContent(body="Привет"))
    assert "login_threads" in str(exc.value)


def test_a_lead_reaching_the_composer_lands_on_manual():
    """The whole point of the exception choice, asserted end to end: SendOutreach
    maps it to manual=True, so the send loop writes `manual` — not a bare failure."""
    from app.application.send_outreach import SendOutreach

    class _Lead:
        target = "@sky"

    res = SendOutreach(ThreadsChannel("s.json", True)).execute(
        _Lead(), OutreachContent(body="Привет"))
    assert res.ok is False
    assert res.manual is True
    assert "login_threads" in res.error
