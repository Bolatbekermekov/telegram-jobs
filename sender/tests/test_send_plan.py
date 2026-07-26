from app.application.send_plan import hold_reason, skip_reason
from app.domain.lead import STATUS_SKIPPED

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
# `run()` has no test harness, so these assert the decision at its seam. The
# loop's part is one `continue` with no mark_status call, so a held lead keeps
# the status it already has — `new`.

def test_a_model_contact_is_held_in_auto_mode():
    """Auto mode has no confirmation, and the confirmation is what checks the
    model's reading of the thread — so the send has to go with it."""
    reason = hold_reason(contact_from_model=True, auto_send=True)
    assert reason is not None
    assert "new" in reason, "человеку должно быть сказано, что лид остаётся 'new'"


def test_a_rules_contact_is_sent_in_auto_mode():
    """The carve-out is narrow: deterministic detection is untouched by it."""
    assert hold_reason(contact_from_model=False, auto_send=True) is None


def test_interactive_mode_is_never_held():
    """Nothing changes when a human confirms: they see the contact, they are told
    it came from the model, and s/k/q is already their decision."""
    assert hold_reason(contact_from_model=True, auto_send=False) is None
    assert hold_reason(contact_from_model=False, auto_send=False) is None
