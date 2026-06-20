"""Map a Telegram command to the search platform it requests (or None)."""


def command_to_search_platform(text: str):
    t = text.strip()
    if t.startswith("/search_linkedin"):
        return "linkedin"
    if t.startswith("/search_wellfound"):
        return "wellfound"
    if t.startswith("/start_search"):
        return "all"
    return None
