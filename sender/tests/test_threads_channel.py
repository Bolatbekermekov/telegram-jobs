"""ThreadsChannel is the DM fallback: used only when the thread carried no contact."""
import pytest

from app.domain.channel import ChannelUnavailable, ManualApplyRequired, OutreachContent
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
    than guessing them. Until Task 10 does that, reaching the composer must raise
    the project's own "couldn't be automated" signal."""
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
