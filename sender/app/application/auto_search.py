"""Decide whether the worker should fire its periodic all-platform search."""


def should_auto_search(last_run, now, every_hours: int) -> bool:
    """True if no auto-search has run yet, or `every_hours` have elapsed."""
    if last_run is None:
        return True
    return (now - last_run).total_seconds() >= every_hours * 3600
