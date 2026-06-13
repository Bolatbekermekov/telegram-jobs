from app.application.send_outreach import SendOutreach
from app.domain.channel import OutreachContent, RateLimitedError
from app.domain.lead import Lead


class _FakeChannel:
    name = "fake"
    body_limit = None
    needs_subject = False

    def __init__(self, raise_exc=None):
        self.sent = []
        self._raise = raise_exc

    def start(self): ...
    def stop(self): ...

    def send(self, target, content):
        if self._raise:
            raise self._raise
        self.sent.append((target, content))


def _lead():
    return Lead(row=2, lead_id="1", platform="fake", target="@x",
                vacancy_context="v", raw_text="r", status="new")


def test_sends_content_to_target():
    ch = _FakeChannel()
    result = SendOutreach(ch).execute(_lead(), OutreachContent(body="hello"))
    assert result.ok
    assert ch.sent == [("@x", OutreachContent(body="hello"))]


def test_captures_error():
    ch = _FakeChannel(raise_exc=ValueError("boom"))
    result = SendOutreach(ch).execute(_lead(), OutreachContent(body="hi"))
    assert not result.ok
    assert "boom" in result.error
    assert result.rate_limited is False


def test_flags_rate_limit():
    ch = _FakeChannel(raise_exc=RateLimitedError("blocked"))
    result = SendOutreach(ch).execute(_lead(), OutreachContent(body="hi"))
    assert not result.ok
    assert result.rate_limited is True
