"""Build the right searcher for a platform (mirrors channels/registry.py)."""
from app import config
from app.infrastructure.search.linkedin_search import LinkedInSearcher
from app.infrastructure.search.wellfound_search import WellfoundSearcher


def build_searcher(platform: str):
    if platform == "linkedin":
        return LinkedInSearcher(
            config.LINKEDIN_STATE_PATH,
            headless=config.BROWSER_HEADLESS,
            people_enabled=config.LINKEDIN_PEOPLE_ENABLED,
        )
    if platform == "wellfound":
        return WellfoundSearcher(
            config.WELLFOUND_STATE_PATH,
            headless=config.BROWSER_HEADLESS,
        )
    raise ValueError(f"no searcher for platform: {platform}")
