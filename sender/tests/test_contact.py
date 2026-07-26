"""Contact detection, sender-side copy. Used by the Threads resolver to find the
real contact inside a rendered thread."""
from app.domain.contact import Contact, detect_contact


def test_telegram_handle():
    assert detect_contact("Пиши @ivan_hr") == Contact("telegram", "@ivan_hr")


def test_telegram_handle_with_a_stray_space_after_the_at():
    """Threads renders a mention as '@ skyluckwalker' — one glued token in the DOM
    text. The real contact must survive that."""
    c = detect_contact("Для отклика присылайте портфолио в Telegram: @ skyluckwalker")
    assert c == Contact("telegram", "@skyluckwalker")


def test_tme_link():
    c = detect_contact("контакт https://t.me/ivanhr")
    assert c.platform == "telegram" and "t.me/ivanhr" in c.target


def test_email():
    assert detect_contact("резюме на hr@acme.com") == Contact("email", "hr@acme.com")


def test_plain_email_is_not_telegram():
    assert detect_contact("john@gmail.com").platform == "email"


def test_linkedin():
    assert detect_contact("linkedin.com/in/ivan").platform == "linkedin"


def test_hh():
    assert detect_contact("https://hh.ru/vacancy/12345").platform == "hh"


def test_regional_hh_is_folded_onto_hh_ru():
    """The saved hh session is hh.ru-only; a regional link dead-ends at the login
    wall. A thread saying "откликнуться на hh.kz/vacancy/…" must not walk into it."""
    c = detect_contact("откликнуться https://astana.hh.kz/vacancy/135297431?from=x")
    assert c.target == "https://hh.ru/vacancy/135297431"


def test_wellfound():
    assert detect_contact("https://wellfound.com/jobs/1-dev").platform == "wellfound"


def test_priority_telegram_over_email():
    assert detect_contact("@ivan_hr или boss@acme.com").platform == "telegram"


def test_none_when_no_contact():
    assert detect_contact("просто описание вакансии") is None


def test_strips_trailing_punctuation():
    assert detect_contact("см. (linkedin.com/in/abc).").target.endswith("abc")
