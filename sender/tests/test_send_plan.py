from app.application.send_plan import has_placeholder, hold_reason, skip_reason
from app.domain.lead import STATUS_MANUAL, STATUS_SKIPPED

_KNOWN_T = {"telegram", "linkedin", "hh"}


class _Lead:
    def __init__(self, platform):
        self.platform = platform


def test_skip_unknown_platform():
    assert skip_reason(_Lead("myspace"), _KNOWN_T) == (
        STATUS_SKIPPED, "unknown platform: myspace")


def test_no_skip_for_known_platform():
    assert skip_reason(_Lead("telegram"), _KNOWN_T) is None


def test_platform_matching_is_exact():
    """A near-miss name is unknown, not silently accepted."""
    assert skip_reason(_Lead("Telegram"), _KNOWN_T) == (
        STATUS_SKIPPED, "unknown platform: Telegram")


# --- holding an unattended send back --------------------------------------
# `run()` has no test harness, so these assert the decision at its seam, which
# now includes the STATUS the loop writes. The loop's own part is two identical
# call sites: mark_status(lead, status, note=note) then `continue`.

_URL = "https://www.threads.com/@lnkrnchk/post/DbL4LxBl6v9"
_REVIEW = "контакт предложен моделью, а не правилами — нужна проверка человеком"


def test_a_contact_needing_review_is_held_as_manual_in_auto_mode():
    """Auto mode has no confirmation, and the confirmation is what checks how the
    contact was arrived at — so the send has to go with it."""
    held = hold_reason(auto_send=True, review=_REVIEW,
                       contact="telegram → @acmecorp", source_url=_URL)
    assert held is not None
    status, note = held
    assert status == STATUS_MANUAL, "`new` был бы подхвачен и отправлен следующим прогоном"
    assert _REVIEW in note


def test_the_held_note_carries_the_contact_and_the_thread():
    """Everything needed to act by hand: the row shows only where the lead points."""
    _, note = hold_reason(auto_send=True, review=_REVIEW,
                          contact="telegram → @acmecorp", source_url=_URL)
    assert "@acmecorp" in note
    assert _URL in note


def test_an_unambiguous_contact_is_sent_in_auto_mode():
    """The carve-out is narrow: a detection the resolver did not flag just goes."""
    assert hold_reason(auto_send=True, review="") is None


def test_interactive_mode_is_never_held():
    """Nothing changes when a human confirms: they are shown the reason, and
    s/k/q is already their decision."""
    assert hold_reason(auto_send=False, review=_REVIEW) is None
    assert hold_reason(auto_send=False) is None


# --- placeholders are a different animal ----------------------------------
# Deliberately not a `manual` hold: the body is regenerated from scratch on every
# run, so leaving the lead `new` self-heals for free.

def test_a_placeholder_is_detected():
    """README promised auto mode catches this; the loop only warned, and only in
    manual mode, so a template could reach a live recruiter."""
    assert has_placeholder("Здравствуйте! [почему именно эта компания]")
    assert has_placeholder("Привет, [название компании]!")
    assert has_placeholder("Hi, [your name] here")


def test_a_bracketed_proper_noun_is_not_a_placeholder():
    """`"[" in body` parked a lead for quoting a job title. It must not."""
    assert not has_placeholder("Видел вакансию [Senior Dev] — очень интересно.")
    assert not has_placeholder("Откликаюсь на [Python Backend Engineer].")


def test_a_clean_body_has_no_placeholder():
    assert not has_placeholder("Здравствуйте! Меня зовут Болатбек.")
    assert not has_placeholder("")
