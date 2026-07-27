"""Per-lead gating for the id-order send loop.

Leads are sent in sheet order (by id). Before opening a channel for a lead we
ask skip_reason() whether it should be skipped — so a skip never causes a
channel switch. Only an unknown platform qualifies: channel-start failures and
mid-run rate limits are handled by the loop itself, which leaves those leads
`new` rather than writing a terminal status.
"""
import re

from app.domain.lead import STATUS_MANUAL, STATUS_SKIPPED


def skip_reason(lead, known) -> tuple[str, str] | None:
    """Why this lead can't be sent right now, as (status, note), or None to send.

    Only an unknown platform is a per-lead skip. Two other failures are handled
    in the send loop instead: a channel that won't start stops the whole run
    (the lead was never attempted, so it stays `new`), and a platform that
    rate-limited us mid-run leaves its remaining leads `new` for the next run.
    """
    p = lead.platform
    if p not in known:
        return (STATUS_SKIPPED, f"unknown platform: {p}")
    return None


def hold_reason(auto_send: bool, review: str = "", contact: str = "",
                source_url: str = "") -> tuple[str, str] | None:
    """Why an unattended run must not send this lead, as (status, note), or None.

    `review` is the resolver's verdict on the contact — non-empty when a human has
    to look before it goes out, and already phrased for a human (see
    `resolve_threads_lead.REVIEW_MODEL`). Auto mode has no
    confirmation step, so a contact nobody has read must not be sent; interactive
    runs show the same reason and let the human decide.

    The status is `manual`, not `new`. `new` does not survive here: by this point
    the row has already been rewritten to an ordinary platform, so the next run
    would find a normal lead, resolve nothing, raise no flag and auto-send it
    unread — the hold would last exactly one run. `manual` is outside
    `fetch_new_leads`, it says the truth ("needs a person"), and it is not the
    terminal `skipped` the human forbade. The cost: getting such a lead back into
    the queue means setting Статус to `new` in the sheet by hand, because nothing
    in the sender writes that value to an existing row.

    Deliberately NOT the same treatment as `has_placeholder` below: a contact is
    decided once and sticks, a message body is regenerated from scratch every run.

    The note carries what acting by hand needs — why it stopped, what it would
    have been sent to, and where that came from — because the row itself only
    shows where the lead now points.
    """
    if not auto_send or not review:
        return None
    parts = [review]
    if contact:
        parts.append(f"контакт: {contact}")
    if source_url:
        parts.append(f"тред: {source_url}")
    return STATUS_MANUAL, "; ".join(parts)


def thread_unread(target: str, source_url: str) -> bool:
    """True when resolving left the lead untouched, i.e. the thread never rendered.

    `resolve_threads_lead` hands the lead back exactly as it came when `render`
    returns "" — a login wall, a timeout or a network blip, all expected — and
    writes no status, deliberately, so the lead stays `new` and the next run tries
    again. The only visible trace of that is the target: it is still the post URL
    it arrived as, rather than the author handle or a contact found in the thread.

    Two callers need it and must agree, hence one definition:
      * `dm_fallback_reason` — an unread thread is not a DM-fallback lead, so the
        no-session gate must not park it as `manual`;
      * the send loop — which must `continue` on it instead of falling through to
        the channel. Falling through is not harmless: with no session
        `ThreadsChannel.start()` raises `ChannelUnavailable`, which the loop answers
        with `SystemExit(1)`, killing the run for every other platform too; with a
        session it would DM the author off the root post alone, without the vacancy
        text and the contact that the unread self-replies were supposed to carry.
    """
    return bool(source_url) and target == source_url


def dm_fallback_reason(platform: str, session_live, author: str = "",
                       source_url: str = "") -> tuple[str, str] | None:
    """Why the Threads DM fallback can't even be attempted, as (status, note), or None.

    Only ever true of a lead the resolver actually put on the DM fallback: its thread
    was read, named no contact at all, and so the lead stayed on `threads` pointing at
    its author — the weakest route in the feature and the one everything else is built
    to avoid needing.

    Checked BEFORE the channel is opened, which is the whole point. `ThreadsChannel.
    start()` answers a dead session with `ChannelUnavailable`, and the send loop
    answers that with `SystemExit(1)` — right for a channel that is supposed to work
    (a broken session must not go unnoticed while the healthy platforms drain), wrong
    for this one, where "no session" is the expected state until a burner Instagram
    exists and possibly forever, since the human may decide never to create one. One
    contactless Threads lead must not take Telegram, hh and every other platform's
    leads down with it.

    `author` is `lead.target` after resolving, `source_url` the thread URL it pointed
    at before. When they are still equal the resolve did NOT happen — `render` failed
    (login wall, timeout, network blip, all expected) and `resolve_threads_lead` handed
    the lead back untouched, deliberately, so that it stays `new` and the next run
    tries again. That lead is not on the DM fallback and must not be gated: parking it
    as `manual` would forfeit the retry and, with it, the better outcome behind the
    retry — the next render may find a real contact in a self-reply and send over
    Telegram, never touching this channel at all. A thread that never renders is
    retried every run and never sent; that is visible in the sheet and consistent with
    how a failed generation is already handled.

    `session_live() -> bool` is a callable, not a bool, and is consulted last, so no
    lead that is not on the DM fallback reads the Threads state file at all.

    The status is `manual`, for the same reason `hold_reason` uses it: it is outside
    `fetch_new_leads`, it says the truth ("needs a person"), and it is not the
    terminal `skipped` the human forbade. `new` would be worse than useless HERE —
    unlike the unresolved case above, nothing about the next run is different, so the
    lead would hit the same wall every time, silently, forever.

    The note carries both ways out, because there are genuinely two: log in, or send
    it yourself. `author` is what the row's Источник now holds.
    """
    if platform != "threads":
        return None
    if thread_unread(author, source_url):
        return None                      # thread unread — still `new`, retried later
    if session_live():
        return None
    parts = ["сессии Threads нет — DM автору отправить нечем",
             "выполни `make login_threads` на отдельном (burner) Instagram"]
    if author:
        parts.append(f"или напиши автору вручную: {author}")
    return STATUS_MANUAL, "; ".join(parts)


# A slot the writer was supposed to fill: bracketed prose starting in lower case
# ("[почему именно эта компания]", "[название компании]", "[your name]"). The
# lower-case start is what separates it from a bracketed proper noun the letter
# legitimately quotes — "вакансию [Senior Dev]" must not park a lead.
_PLACEHOLDER_RE = re.compile(r"\[\s*[a-zа-яё][^\]\n]*\]")


def has_placeholder(body: str) -> bool:
    """True when the generator left a `[плейсхолдер]` in the message.

    Unlike `hold_reason`, the caller writes NO status for this: the body is a
    per-generation artifact, `generate_body` runs fresh on every run, so leaving
    the lead `new` self-heals for free on the next one. Writing `manual` here
    would charge a hand-edit in Sheets for what a re-roll fixes.
    """
    return bool(_PLACEHOLDER_RE.search(body or ""))
