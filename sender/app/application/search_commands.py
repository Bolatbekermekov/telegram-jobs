"""Map a CLI subcommand token to the concrete platforms to search."""
from app.domain.search_request import platforms_for

_TOKEN_TO_PLATFORM = {
    "search": "all",
    "search_linkedin": "linkedin",
    "search_wellfound": "wellfound",
    "search_remoteok": "remoteok",
    "search_remotive": "remotive",
    "search_hh": "hh",
}


def platforms_arg(token: str) -> list[str]:
    return platforms_for(_TOKEN_TO_PLATFORM[token])
