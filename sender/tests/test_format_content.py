from app.application.format_content import format_for_channel
from app.domain.channel import OutreachContent


class _Ch:
    def __init__(self, body_limit=None, needs_subject=False):
        self.name = "x"
        self.body_limit = body_limit
        self.needs_subject = needs_subject


def test_passes_body_through_when_no_limit():
    c = format_for_channel(_Ch(), body="hello world", subject="S", attachment_path="cv.pdf")
    assert c == OutreachContent(body="hello world", subject=None, attachment_path="cv.pdf")


def test_truncates_at_word_boundary_within_limit():
    ch = _Ch(body_limit=10)
    c = format_for_channel(ch, body="hello world foo", subject=None, attachment_path=None)
    assert len(c.body) <= 10
    assert c.body == "hello"  # cut at the last space before the limit


def test_hard_cut_when_no_space():
    ch = _Ch(body_limit=4)
    c = format_for_channel(ch, body="abcdefgh", subject=None, attachment_path=None)
    assert c.body == "abcd"


def test_subject_kept_only_when_needed():
    ch = _Ch(needs_subject=True)
    c = format_for_channel(ch, body="b", subject="Hi there", attachment_path=None)
    assert c.subject == "Hi there"
