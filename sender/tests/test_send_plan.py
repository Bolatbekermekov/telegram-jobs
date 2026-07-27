from app.application.send_plan import (
    dm_fallback_reason,
    has_placeholder,
    hold_reason,
    skip_reason,
    unresolved_thread,
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
    gated = dm_fallback_reason("threads", lambda: False,
                               author="@lnkrnchk", source_url=_URL)
    assert gated is not None
    status, _ = gated
    assert status == STATUS_MANUAL, "`skipped` — терминальный статус, который человек запретил"


def test_the_gated_note_carries_both_routes_out():
    """Acting by hand needs both doors: log in, or write to the author yourself."""
    _, note = dm_fallback_reason("threads", lambda: False,
                                 author="@lnkrnchk", source_url=_URL)
    assert "login_threads" in note
    assert "@lnkrnchk" in note


def test_a_live_session_lets_the_lead_reach_the_channel():
    assert dm_fallback_reason("threads", lambda: True,
                              author="@lnkrnchk", source_url=_URL) is None


def test_a_resolved_contact_is_not_gated_and_never_reads_the_threads_state():
    """The thread named a real contact, so the lead now goes out over Telegram —
    whether a Threads burner exists is none of its business."""
    calls = []

    def _session():
        calls.append(1)
        return False

    assert dm_fallback_reason("telegram", _session,
                              author="@acmecorp", source_url=_URL) is None
    assert calls == [], "состояние Threads читается только для threads-лида"


# The carve-out: a lead still pointing at the POST is not a DM-fallback lead, it is
# a lead that has not been resolved yet. `resolve_threads_lead` hands it back
# untouched on a render failure — login wall, timeout, network blip — precisely so
# it stays `new` and the next run tries again. Gating it to `manual` would forfeit
# that retry AND the good outcome behind it: the next render may find a real contact
# in a self-reply and send over Telegram, never touching the DM fallback at all.
#
# The question is asked of the target's SHAPE, not of value identity with the URL the
# lead arrived as. Identity was wrong: a lead already resolved onto the DM fallback
# has Источник=@hr_acme, `render` refuses it (author_from_url wants a /post/ URL),
# the resolver hands it back untouched, and target == source_url all over again —
# so the re-queued lead read as "never rendered" and was stuck `new` forever.


def test_an_unrendered_thread_stays_new_for_the_next_run():
    """Target is still a post URL => there is nobody to write to yet."""
    assert dm_fallback_reason("threads", lambda: False,
                              author=_URL, source_url=_URL) is None


def test_an_unrendered_thread_is_not_gated_even_with_a_live_session():
    """Nothing about the session makes an unread thread sendable — it has no
    author handle to DM. It is `new` either way."""
    assert dm_fallback_reason("threads", lambda: True,
                              author=_URL, source_url=_URL) is None


def test_an_unrendered_thread_never_reads_the_threads_state_either():
    """The retry is decided before the session is: no state file read for a lead
    that is not on the DM fallback, whichever way it failed to get there."""
    calls = []

    def _session():
        calls.append(1)
        return False

    assert dm_fallback_reason("threads", _session,
                              author=_URL, source_url=_URL) is None
    assert calls == [], "нерезолвленный тред — не DM-фолбэк, сессия ни при чём"


# --- the re-queued lead: the recovery this whole task exists to create ----------
# The gate note tells the human to run `make login_threads` and put Статус back to
# `new`. The row it comes back on holds Платформа=threads, Источник=@hr_acme.


def test_a_requeued_dm_fallback_lead_is_gated_again_when_there_is_still_no_session():
    gated = dm_fallback_reason("threads", lambda: False,
                               author="@hr_acme", source_url="@hr_acme")
    assert gated is not None
    assert gated[0] == STATUS_MANUAL


def test_a_requeued_dm_fallback_lead_reaches_the_channel_once_a_session_exists():
    """The point of re-queueing. Reading this as "тред не прочитался" and skipping
    it left the lead permanently unsendable — the human logs in, re-queues, and
    nothing ever happens."""
    assert dm_fallback_reason("threads", lambda: True,
                              author="@hr_acme", source_url="@hr_acme") is None


def test_a_resolved_author_is_never_confused_with_a_post_url():
    """The discriminator: a handle is somebody to write to, a /post/ URL is not."""
    assert unresolved_thread(_URL) is True
    assert unresolved_thread("https://www.threads.net/@hr.acme/post/Z") is True
    assert unresolved_thread("@hr_acme") is False
    assert unresolved_thread("hr_acme") is False


def test_a_profile_url_without_a_post_is_not_a_thread_to_read():
    """author_from_url wants the /post/ segment, so a bare profile URL is not an
    unread thread — there is nothing to render there."""
    assert unresolved_thread("https://www.threads.com/@hr_acme") is False
    assert unresolved_thread("") is False


def test_a_different_post_url_is_still_unresolved():
    """Not identity with THIS lead's source: any /post/ URL means the lead still
    points at a thread rather than at a person, however it got there."""
    assert unresolved_thread("https://www.threads.com/@someone/post/DIFFERENT") is True


# --- the note has to survive the row being overwritten -------------------------


def test_the_gated_note_keeps_a_pointer_to_the_thread():
    """update_resolved has already replaced Источник with the handle and mark_status
    overwrites Заметка, which held «…DM автору: <URL>». Without the URL here the
    human is told to write to @hr_acme by hand and can no longer open the post to
    read what the vacancy even is."""
    _, note = dm_fallback_reason("threads", lambda: False,
                                 author="@lnkrnchk", source_url=_URL)
    assert _URL in note


def test_the_note_does_not_repeat_the_handle_as_a_thread_url():
    """On a re-queued lead the source is the handle, not a URL — appending it as
    «тред: @hr_acme» would add nothing and read as a broken link."""
    _, note = dm_fallback_reason("threads", lambda: False,
                                 author="@hr_acme", source_url="@hr_acme")
    assert "тред:" not in note
    assert note.count("@hr_acme") == 1


def test_the_note_without_an_author_offers_only_the_login_route():
    """The `if author:` false branch: no handle to offer, so the note must stop
    cleanly rather than trail off into «напиши автору вручную: »."""
    _, note = dm_fallback_reason("threads", lambda: False, author="", source_url=_URL)
    assert "login_threads" in note
    assert "вручную" not in note
    assert _URL in note


# --- placeholders are a different animal ----------------------------------
# Deliberately not a `manual` hold: the body is regenerated from scratch on every
# run, so leaving the lead `new` self-heals for free.

def test_a_placeholder_is_detected():
    """README promised auto mode catches this; the loop only warned, and only in
    manual mode, so a template could reach a live recruiter."""
    assert has_placeholder("Здравствуйте! [почему именно эта компания]")
    assert has_placeholder("Привет, [название компании]!")
    assert has_placeholder("Hi, [your name] here")


def test_a_capitalised_placeholder_is_detected_too():
    """The four probes that showed README's [!CAUTION] promise was false.

    The net used to require a lower-case first letter, so only the first of these
    was caught and the other three were AUTO-SENT to a live recruiter. That is
    backwards: a model writing a Russian cover letter capitalises a bracketed slot
    opening a sentence essentially always, so the capitalised forms are the common
    shape, not the exotic one.
    """
    assert has_placeholder("Здравствуйте, [название компании]!")
    assert has_placeholder("Здравствуйте, [Название компании]!")
    assert has_placeholder("[Your name]")
    assert has_placeholder("[ПОЧЕМУ ИМЕННО ЭТА КОМПАНИЯ]")


def test_a_bracketed_proper_noun_now_holds_the_lead_too():
    """The accepted price of the case-insensitive net, pinned as a decision rather
    than left as a surprise: a job title the letter legitimately quotes reads as a
    placeholder. It costs ONE regeneration and nothing else — `has_placeholder`
    writes no status, so the lead stays `new` and the body is generated afresh next
    run — against a false negative that costs a template in a recruiter's inbox.
    Not a livelock either: the generator is instructed to write names as plain text
    without brackets, so this is a stray shape, not the model's habit.
    """
    assert has_placeholder("Видел вакансию [Senior Dev] — очень интересно.")
    assert has_placeholder("Откликаюсь на [Python Backend Engineer].")


def test_a_clean_body_has_no_placeholder():
    assert not has_placeholder("Здравствуйте! Меня зовут Болатбек.")
    assert not has_placeholder("")
