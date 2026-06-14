"""Search-request entity exchanged via the «Команды» tab. No external deps."""
from dataclasses import dataclass

REQ_PENDING = "pending"
REQ_RUNNING = "running"
REQ_DONE = "done"
REQ_ERROR = "error"

# Platforms searchable in sub-project C, in scrape order.
SEARCH_PLATFORMS = ["linkedin", "wellfound"]


@dataclass
class SearchRequest:
    id: str
    platform: str   # all | linkedin | wellfound
    status: str


def platforms_for(platform: str) -> list[str]:
    """Expand a request's platform field into the concrete platforms to scrape."""
    if platform == "all":
        return list(SEARCH_PLATFORMS)
    return [platform]
