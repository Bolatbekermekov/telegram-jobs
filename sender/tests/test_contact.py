"""Contact detection, sender-side copy. Used by the Threads resolver to find the
real contact inside a rendered thread."""
from app.domain.contact import Contact, detect_contact


def test_telegram_handle():
    assert detect_contact("Пиши @ivan_hr") == Contact("telegram", "@ivan_hr")


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


def test_a_bare_threads_post_url_yields_no_contact():
    """The one sanctioned difference from the intake copy, pinned.

    There is deliberately no `threads` rule here: by the time this runs the lead is
    already threads, so a rule would re-point it at itself. Nothing else locks that,
    so without this assertion a future refresh copied from intake could reintroduce a
    `threads` rule and leave the suite green.
    """
    assert detect_contact("https://www.threads.com/@lnkrnchk/post/DbL4LxBl6v9") is None


# --- Golden parity vectors ---------------------------------------------------
# This table is checked into BOTH suites — sender/tests/test_contact.py and
# intake-bot/tests/test_detect_contact.py — with identical data, deliberately
# duplicated. The two apps are separate deploys that never import each other, so the
# only thing that catches a drift in one of the two `contact.py` copies is each suite
# pinning the answers itself. Change one copy of this table, change the other.
#
# It exists because the sender copy diverged behaviourally from the intake original on
# the day it was created: a handle rule widened to `@\s?` also matched the "at" of
# "hr @ acme.com" and "Role @ Company" and returned a fabricated "@acme" target,
# pre-empting the email, linkedin and hh rules that held the real contact. A
# hand-written parity check missed it because its inputs contained no "X @ domain.tld"
# and no prose "@". The last four rows are that shape.
#
# Threads URLs are deliberately kept out: a Threads link legitimately changes the
# answer between the apps (intake has a `threads` rule and an author exemption, the
# sender has neither by design), so no single expectation could hold for both. Threads
# behaviour is pinned per-app instead, outside this table.
_GOLDEN = [
    # (text, expected platform, expected target) — a None platform means no contact.
    ("Контакт: https://t.me/ivanhr спасибо", "telegram", "https://t.me/ivanhr"),
    ("Ищем backend. Пиши @ivan_hr по вакансии", "telegram", "@ivan_hr"),
    ("резюме на hr@acme.com", "email", "hr@acme.com"),
    # _EMAIL_RE's tail class `[\w.-]+` eats the period that ended the sentence, so
    # without `_clean` the target is "hr@acme.io." — which most MTAs reject at
    # RCPT TO, landing the lead `failed` with the recruiter never contacted. Newly
    # load-bearing: Threads prose is the first free text detect_contact reads, and
    # prose ends its sentences with periods.
    ("резюме на hr@acme.io.", "email", "hr@acme.io"),
    # The (?:^|\s) anchor: the "@" inside a well-formed email is not a handle.
    ("john@gmail.com", "email", "john@gmail.com"),
    # Ordering: the handle rule is second of six, so a later handle beats an earlier email.
    ("пиши boss@acme.com или @ivan_hr", "telegram", "@ivan_hr"),
    ("профиль https://linkedin.com/in/ivan", "linkedin", "https://linkedin.com/in/ivan"),
    ("см. (linkedin.com/in/abc).", "linkedin", "linkedin.com/in/abc"),
    # Regional domain folded onto hh.ru (the saved session is hh.ru-only), tracking dropped.
    ("откликнуться https://astana.hh.kz/vacancy/135297431?from=share_ios",
     "hh", "https://hh.ru/vacancy/135297431"),
    # The vacancy wins over the app-download footer in the same share.
    ("Вакансия: https://hh.kz/vacancy/135297431 Отправлено из мобильного приложения hh"
     " https://hh.ru/mobile", "hh", "https://hh.ru/vacancy/135297431"),
    ("https://wellfound.com/jobs/1-dev", "wellfound", "https://wellfound.com/jobs/1-dev"),
    ("просто описание вакансии", None, None),
    # "@" as the word "at", and space-obfuscated emails. A widened handle rule turns
    # every one of these into a fabricated Telegram target, and in three of the four
    # the real contact is sitting later in the same text.
    ("Резюме отправляйте: hr @ acme.com", None, None),
    ("пишите hr @ acme.com или в телеграм @ivan_hr", "telegram", "@ivan_hr"),
    ("Ищем разработчика @ Astana, откликайтесь на hh.ru/vacancy/12345",
     "hh", "https://hh.ru/vacancy/12345"),
    ("CV -> hr @ acme.com или https://linkedin.com/in/ivan",
     "linkedin", "https://linkedin.com/in/ivan"),
    # A Telegram username cannot contain a dot, so "@maria.hr" is provably not a
    # Telegram target — it is an Instagram/Threads handle. The capture stops at the
    # dot, so taking the match stored "@maria": a real, unrelated user who was never
    # written in the message. The author exemption did not cover this — it is
    # author-relative, and maria is nobody's author. Refusing and falling through is
    # the answer; when no other rule answers either, the intake says it found no
    # contact and asks for a resend, which beats messaging the wrong person.
    ("пиши @maria.hr", None, None),
    # The refusal is per handle, not per message: a real handle later in the same
    # text still wins.
    ("пиши @maria.hr или @ivan_hr", "telegram", "@ivan_hr"),
    # The other direction, and the reason the rule looks at what FOLLOWS the dot:
    # Instagram/Threads handles are ASCII, so a dot followed by non-ASCII cannot be
    # a handle continuing — it is a period whose space the writer forgot. This is a
    # plain "@ivan" and must not be refused along with the dotted handles.
    ("пиши @ivan.Пиши в личку", "telegram", "@ivan"),
    # Same guard from the other end: a TRAILING dot is sentence punctuation, not
    # part of a handle, so this stays an ordinary Telegram contact.
    ("пиши @ivan_hr.", "telegram", "@ivan_hr"),
]


def test_golden_parity_vectors():
    """Every rule, and the ordering between them, pinned as data. Reports every
    drifted vector at once rather than stopping at the first."""
    drift = []
    for text, platform, target in _GOLDEN:
        expected = None if platform is None else (platform, target)
        c = detect_contact(text)
        actual = None if c is None else (c.platform, c.target)
        if actual != expected:
            drift.append(f"  {text!r}\n    expected {expected}\n    got      {actual}")
    assert not drift, "detect_contact drifted from the golden vectors:\n" + "\n".join(drift)
