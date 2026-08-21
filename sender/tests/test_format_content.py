from app.application.format_content import format_for_channel
from app.domain.channel import OutreachContent


class _Ch:
    def __init__(self, body_limit=None, needs_subject=False, signature_drop=()):
        self.name = "x"
        self.body_limit = body_limit
        self.needs_subject = needs_subject
        self.signature_drop = signature_drop


_SIGNED = (
    "Здравствуйте, Анна.\n\nМой стек: Python, TypeScript.\n\n"
    "С уважением, Bolatbek\n"
    "Telegram: @bolatbekermeko_v\n"
    "Email: ermekovbolatbek50@gmail.com\n"
    "LinkedIn: https://www.linkedin.com/in/bolatbekermekov/"
)


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


def test_the_note_is_carried_through_untouched():
    """Записка живёт по своим правилам: её пишут сразу под лимит площадки, и
    `body_limit` (предел ПИСЬМА) к ней отношения не имеет."""
    ch = _Ch(body_limit=10)
    c = format_for_channel(ch, body="hello world foo", subject=None,
                           attachment_path=None, note="Короткая записка целиком.")
    assert c.note == "Короткая записка целиком."
    assert c.body == "hello"


def test_the_note_defaults_to_empty():
    c = format_for_channel(_Ch(), body="b", subject=None, attachment_path=None)
    assert c.note == ""


def test_channel_drops_its_own_contact_line_from_the_signature():
    """Письмо в LinkedIn не должно нести ссылку на LinkedIn: его читают там же."""
    ch = _Ch(signature_drop=("linkedin",))
    c = format_for_channel(ch, body=_SIGNED, subject=None, attachment_path=None)
    assert "linkedin.com" not in c.body.lower()
    assert "Telegram: @bolatbekermeko_v" in c.body
    assert "Email: ermekovbolatbek50@gmail.com" in c.body
    assert c.body.endswith("Email: ermekovbolatbek50@gmail.com")
    assert c.body.startswith("Здравствуйте, Анна.\n\nМой стек")


def test_a_channel_without_the_attribute_keeps_the_whole_signature():
    """Каналы, не объявившие `signature_drop`, о нём и не знают: подпись целая."""
    class _Bare:
        name = "telegram"
        body_limit = None
        needs_subject = False

    c = format_for_channel(_Bare(), body=_SIGNED, subject=None, attachment_path=None)
    assert c.body == _SIGNED


def test_prose_mentioning_the_platform_survives():
    """Режем только строку-контакт «Label: …», а не слово в тексте письма."""
    ch = _Ch(signature_drop=("linkedin",))
    body = "Нашёл вашу вакансию в LinkedIn Jobs.\n\nLinkedIn: https://example.com/x"
    c = format_for_channel(ch, body=body, subject=None, attachment_path=None)
    assert c.body == "Нашёл вашу вакансию в LinkedIn Jobs."


def test_drop_runs_before_truncation():
    ch = _Ch(body_limit=12, signature_drop=("linkedin",))
    c = format_for_channel(ch, body="LinkedIn: u\nhello world foo", subject=None,
                           attachment_path=None)
    assert c.body == "hello world"
