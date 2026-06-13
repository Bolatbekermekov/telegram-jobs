from email.message import EmailMessage

from app.domain.channel import ChannelError, OutreachContent
from app.infrastructure.channels.email_channel import EmailChannel, build_email


def test_build_email_sets_headers_and_body():
    content = OutreachContent(body="Hello there", subject="Backend role")
    msg = build_email(content, to_addr="r@x.com", from_addr="me@x.com", from_name="Me")
    assert isinstance(msg, EmailMessage)
    assert msg["To"] == "r@x.com"
    assert msg["From"] == "Me <me@x.com>"
    assert msg["Subject"] == "Backend role"
    assert msg.get_content().strip() == "Hello there"


def test_build_email_requires_subject():
    try:
        build_email(OutreachContent(body="x", subject=None),
                    to_addr="r@x.com", from_addr="me@x.com", from_name="Me")
        assert False, "expected ChannelError"
    except ChannelError:
        pass


def test_channel_metadata():
    ch = EmailChannel(host="h", port=587, user="u", password="p", from_name="Me")
    assert ch.name == "email"
    assert ch.needs_subject is True
    assert ch.body_limit is None


def test_send_uses_smtp():
    calls = {}

    class _FakeSMTP:
        def __init__(self, host, port):
            calls["addr"] = (host, port)
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def starttls(self): calls["tls"] = True
        def login(self, u, p): calls["login"] = (u, p)
        def send_message(self, msg): calls["to"] = msg["To"]

    ch = EmailChannel(host="h", port=587, user="me@x.com", password="pw",
                      from_name="Me", smtp_factory=_FakeSMTP)
    ch.send("r@x.com", OutreachContent(body="hi", subject="S"))
    assert calls["addr"] == ("h", 587)
    assert calls["tls"] is True
    assert calls["login"] == ("me@x.com", "pw")
    assert calls["to"] == "r@x.com"
