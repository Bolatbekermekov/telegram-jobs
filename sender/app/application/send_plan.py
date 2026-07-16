"""Ordering for the send loop: process leads one platform at a time.

Browser channels (Playwright) and the Telegram userbot (Telethon, asyncio)
cannot run at the same time in one process — a second live channel collides
with the first one's event loop. So the send loop must open a single channel,
send all of that platform's leads, close it, and only then move on. This
module turns a flat lead list into those per-platform batches.
"""

from app.domain.lead import STATUS_FAILED, STATUS_SKIPPED


def group_leads_by_platform(leads) -> list:
    """[(platform, [leads...]), ...] with platforms in first-appearance order."""
    groups: dict[str, list] = {}
    for lead in leads:
        groups.setdefault(lead.platform, []).append(lead)
    return list(groups.items())


def skip_reason(lead, known, sent_per_platform, daily_limit,
                rate_limited, failed_platforms):
    """Why this lead can't be sent right now, as (status, note), or None to send.

    Checked before any channel opens, so a skip never triggers a channel switch.
    Order: unknown platform, then a platform whose channel already failed this
    run, then one that rate-limited us, then the per-platform daily cap.
    """
    p = lead.platform
    if p not in known:
        return (STATUS_SKIPPED, f"unknown platform: {p}")
    if p in failed_platforms:
        return (STATUS_FAILED, "channel start failed earlier this run")
    if p in rate_limited:
        return (STATUS_SKIPPED, "rate-limited earlier this run")
    if sent_per_platform.get(p, 0) >= daily_limit:
        return (STATUS_SKIPPED, "daily limit reached")
    return None
