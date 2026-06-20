"""Map a CLI subcommand token to the concrete platforms to search."""
from app.domain.search_request import platforms_for

_TOKEN_TO_PLATFORM = {
    "search": "all",
    "search_linkedin": "linkedin",
    "search_wellfound": "wellfound",
}


def platforms_arg(token: str) -> list[str]:
    return platforms_for(_TOKEN_TO_PLATFORM[token])
