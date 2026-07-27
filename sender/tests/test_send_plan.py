from app.application.send_plan import (
    dm_fallback_reason,
    has_placeholder,
    hold_reason,
    skip_reason,
)
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


# --- the DM fallback with no burner session -------------------------------
# Same seam convention as hold_reason above: `run()` has no test harness, so these
# assert the decision, and the loop's part is the same two lines —
# mark_status(lead, status, note=note) then `continue`.


def test_the_dm_fallback_without_a_session_is_manual():
    """The human may never create the burner Instagram — this path is the weak
    fallback the whole feature is built to avoid needing. Without a session the DM
    cannot be attempted at all, and the lead must say so instead of taking the run
    down with it: ChannelUnavailable out of start() is answered with SystemExit(1),
    which would kill Telegram/hh/every other platform's leads in the same run."""
    gated = dm_fallback_reason("threads", lambda: False, author="@lnkrnchk")
    assert gated is not None
    status, _ = gated
    assert status == STATUS_MANUAL, "`skipped` — терминальный статус, который человек запретил"


def test_the_gated_note_carries_both_routes_out():
    """Acting by hand needs both doors: log in, or write to the author yourself."""
    _, note = dm_fallback_reason("threads", lambda: False, author="@lnkrnchk")
    assert "login_threads" in note
    assert "@lnkrnchk" in note


def test_a_live_session_lets_the_lead_reach_the_channel():
    assert dm_fallback_reason("threads", lambda: True, author="@lnkrnchk") is None


def test_a_resolved_contact_is_not_gated_and_never_reads_the_threads_state():
    """The thread named a real contact, so the lead now goes out over Telegram —
    whether a Threads burner exists is none of its business."""
    calls = []

    def _session():
        calls.append(1)
        return False

    assert dm_fallback_reason("telegram", _session, author="@acmecorp") is None
    assert calls == [], "состояние Threads читается только для threads-лида"


def test_an_unknown_author_still_gates_rather_than_sends():
    """A thread whose author could not be parsed is still unsendable without a
    session; the note just has one door instead of two."""
    gated = dm_fallback_reason("threads", lambda: False, author="")
    assert gated is not None
    assert gated[0] == STATUS_MANUAL


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
