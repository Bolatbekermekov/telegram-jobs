"""Search-request entity exchanged via the «Команды» tab. No external deps."""
from dataclasses import dataclass

REQ_PENDING = "pending"
REQ_RUNNING = "running"
REQ_DONE = "done"
REQ_ERROR = "error"

# Platforms searchable in sub-project C, in scrape order.
SEARCH_PLATFORMS = ["linkedin", "wellfound", "remoteok", "remotive", "wwr", "hh"]


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


def per_keyword_limit(total: int, n_keywords: int) -> int:
    """Split the per-platform card budget across keywords (>=1 each).

    Without this the first keyword fills the whole budget and later keywords
    (other roles) never get scraped.
    """
    if n_keywords <= 0:
        return total
    return max(1, total // n_keywords)
