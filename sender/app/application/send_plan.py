"""Per-lead gating for the id-order send loop.

Leads are sent in sheet order (by id). Before opening a channel for a lead we
ask skip_reason() whether it should be skipped (unknown platform, a channel that
already failed this run, a platform that rate-limited us, or the per-platform
daily cap) — so a skip never causes a channel switch.
"""
from app.domain.lead import STATUS_FAILED, STATUS_SKIPPED


def skip_reason(lead, known, sent_per_platform, daily_limit,
                failed_platforms) -> tuple[str, str] | None:
    """Why this lead can't be sent right now, as (status, note), or None to send.

    Order: unknown platform, then a platform whose channel already failed this
    run, then the per-platform daily cap. A platform that rate-limited us mid-run
    is handled in the send loop, not here — its remaining leads are left untouched
    (status stays `new`) so the next run retries them.
    """
    p = lead.platform
    if p not in known:
        return (STATUS_SKIPPED, f"unknown platform: {p}")
    if p in failed_platforms:
        return (STATUS_FAILED, "channel start failed earlier this run")
    if sent_per_platform.get(p, 0) >= daily_limit:
        return (STATUS_SKIPPED, "daily limit reached")
    return None
