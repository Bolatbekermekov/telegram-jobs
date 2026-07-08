"""Ordering for the send loop: process leads one platform at a time.

Browser channels (Playwright) and the Telegram userbot (Telethon, asyncio)
cannot run at the same time in one process — a second live channel collides
with the first one's event loop. So the send loop must open a single channel,
send all of that platform's leads, close it, and only then move on. This
module turns a flat lead list into those per-platform batches.
"""


def group_leads_by_platform(leads) -> list:
    """[(platform, [leads...]), ...] with platforms in first-appearance order."""
    groups: dict[str, list] = {}
    for lead in leads:
        groups.setdefault(lead.platform, []).append(lead)
    return list(groups.items())
