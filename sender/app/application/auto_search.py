"""Decide whether the worker should fire its scheduled all-platform search.

Auto-search runs at fixed local times (default 12:00 / 16:00 / 22:00 in the
worker's configured timezone) — NOT on a rolling interval and NOT on startup.
The worker seeds `last_run` with the current time at boot, so a restart never
triggers a search; a slot only fires when the clock crosses it while running.
"""


def parse_times(spec: str) -> list[tuple[int, int]]:
    """Parse 'HH:MM,HH:MM' into sorted unique (hour, minute) tuples."""
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        h, _, m = part.partition(":")
        out.append((int(h), int(m or 0)))
    return sorted(set(out))


def most_recent_slot(times, now):
    """Latest scheduled datetime <= now today, or None if now precedes them all."""
    past = []
    for h, m in times:
        slot = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if slot <= now:
            past.append(slot)
    return max(past) if past else None


def due_auto_search(times, last_run, now) -> bool:
    """True when today's most recent scheduled slot has not been covered yet."""
    slot = most_recent_slot(times, now)
    if slot is None:
        return False
    return last_run is None or last_run < slot
