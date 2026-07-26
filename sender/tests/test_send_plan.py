from app.application.send_plan import hold_reason, skip_reason
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


def test_a_model_contact_is_held_as_manual_in_auto_mode():
    """Auto mode has no confirmation, and the confirmation is what checks how the
    model read the thread — so the send has to go with it."""
    held = hold_reason(auto_send=True, contact_from_model=True,
                       contact="telegram → @acmecorp", source_url=_URL)
    assert held is not None
    status, note = held
    assert status == STATUS_MANUAL, "`new` был бы подхвачен и отправлен следующим прогоном"
    assert "модел" in note.lower()


def test_the_held_note_carries_the_contact_and_the_thread():
    """Everything needed to act by hand: the row shows only where the lead points."""
    _, note = hold_reason(auto_send=True, contact_from_model=True,
                          contact="telegram → @acmecorp", source_url=_URL)
    assert "@acmecorp" in note
    assert _URL in note


def test_a_rules_contact_is_sent_in_auto_mode():
    """The carve-out is narrow: deterministic detection is untouched by it."""
    assert hold_reason(auto_send=True, contact_from_model=False) is None


def test_a_placeholder_body_is_held_as_manual_in_auto_mode():
    """README promised this; the loop only warned, and only in manual mode."""
    held = hold_reason(auto_send=True, body="Здравствуйте! [почему эта компания]")
    assert held is not None
    status, note = held
    assert status == STATUS_MANUAL
    assert "плейсхолдер" in note


def test_a_clean_body_is_sent_in_auto_mode():
    assert hold_reason(auto_send=True, body="Здравствуйте! Меня зовут Болатбек.") is None


def test_interactive_mode_is_never_held():
    """Nothing changes when a human confirms: they see the contact, they are told
    it came from the model, and s/k/q is already their decision."""
    assert hold_reason(auto_send=False, contact_from_model=True) is None
    assert hold_reason(auto_send=False, body="осталcя [плейсхолдер]") is None
    assert hold_reason(auto_send=False) is None
