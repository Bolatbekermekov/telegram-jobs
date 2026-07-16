from app.domain.channel import (
    ChannelError,
    ChannelUnavailable,
    OutreachContent,
    RateLimitedError,
)


def test_content_defaults():
    c = OutreachContent(body="hi")
    assert c.body == "hi"
    assert c.subject is None
    assert c.attachment_path is None


def test_rate_limited_is_channel_error():
    assert issubclass(RateLimitedError, ChannelError)


def test_channel_unavailable_is_channel_error():
    # A transient "can't start now, retry next run" signal — not a hard failure.
    assert issubclass(ChannelUnavailable, ChannelError)
