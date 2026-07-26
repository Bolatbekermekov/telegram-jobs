"""Per-lead gating for the id-order send loop.

Leads are sent in sheet order (by id). Before opening a channel for a lead we
ask skip_reason() whether it should be skipped — so a skip never causes a
channel switch. Only an unknown platform qualifies: channel-start failures and
mid-run rate limits are handled by the loop itself, which leaves those leads
`new` rather than writing a terminal status.
"""
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


def hold_reason(auto_send: bool, contact_from_model: bool = False, body: str = "",
                contact: str = "", source_url: str = "") -> tuple[str, str] | None:
    """Why an unattended run must not send this lead, as (status, note), or None.

    Auto mode has no confirmation step, so it must not send what no human has
    read. Two things qualify, and they are one rule:

      * a contact the MODEL proposed instead of the rules. The vetting in
        `contact_llm.parse_contact_response` proves the target was WRITTEN in the
        thread; it cannot prove the target is the address to apply to. "hr @
        acmecorp.com" read back as the handle @acmecorp passes every check, and so
        does a handle the author only mentioned in passing.
      * a body still carrying a `[плейсхолдер]`: the letter was asked for filled
        in and came back a template, and a recruiter must not receive one.

    Both are what a human catches on the confirmation prompt, so taking the
    confirmation away has to take the send away with it.

    The status is `manual`, not `new`. `new` does not survive here: by this point
    the row has already been rewritten to an ordinary platform, so the next run
    would find a normal lead, resolve nothing, raise no flag and auto-send it
    unread — the hold would last exactly one run. `manual` is outside
    `fetch_new_leads`, it says the truth ("needs a person"), and it is not the
    terminal `skipped` the human forbade. The cost: getting such a lead back into
    the queue means setting Статус to `new` in the sheet by hand, because nothing
    in the sender writes that value to an existing row.

    The note carries what acting by hand needs — why it stopped, what it would
    have been sent to, and where that came from — because the row itself only
    shows where the lead now points.
    """
    if not auto_send:
        return None
    if contact_from_model:
        reason = "контакт предложен моделью, а не правилами — нужна проверка человеком"
    elif "[" in body:
        reason = "в тексте остался [плейсхолдер] — нужна правка человеком"
    else:
        return None

    parts = [reason]
    if contact:
        parts.append(f"контакт: {contact}")
    if source_url:
        parts.append(f"тред: {source_url}")
    return STATUS_MANUAL, "; ".join(parts)
