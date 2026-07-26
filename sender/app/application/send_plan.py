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
    `resolve_threads_lead.REVIEW_MODEL` / `REVIEW_UNCUED`). Auto mode has no
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
