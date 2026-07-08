"""Build the right searcher for a platform (mirrors channels/registry.py)."""
from app import config
from app.infrastructure.search.hh_search import HHSearcher
from app.infrastructure.search.linkedin_search import LinkedInSearcher
from app.infrastructure.search.remoteok_search import RemoteOKSearcher
from app.infrastructure.search.remotive_search import RemotiveSearcher
from app.infrastructure.search.wellfound_search import WellfoundSearcher
from app.infrastructure.search.wwr_search import WWRSearcher


def build_searcher(platform: str):
    if platform == "linkedin":
        return LinkedInSearcher(
            config.LINKEDIN_STATE_PATH,
            headless=config.BROWSER_HEADLESS,
            people_enabled=config.LINKEDIN_PEOPLE_ENABLED,
            experience=config.LINKEDIN_EXPERIENCE,
            posted_within=config.LINKEDIN_POSTED_WITHIN,
        )
    if platform == "wellfound":
        return WellfoundSearcher(
            config.WELLFOUND_STATE_PATH,
            headless=config.BROWSER_HEADLESS,
            cdp_url=config.WELLFOUND_CDP_URL,
        )
    if platform == "remoteok":
        return RemoteOKSearcher(
            api_url=config.REMOTEOK_API_URL,
            user_agent=config.HTTP_USER_AGENT,
            timeout=config.HTTP_TIMEOUT_SECONDS,
        )
    if platform == "remotive":
        return RemotiveSearcher(
            api_url=config.REMOTIVE_API_URL,
            user_agent=config.HTTP_USER_AGENT,
            timeout=config.HTTP_TIMEOUT_SECONDS,
        )
    if platform == "wwr":
        return WWRSearcher()  # headful (Cloudflare); no login needed
    if platform == "hh":
        return HHSearcher(config.HH_STATE_PATH, headless=config.BROWSER_HEADLESS)
    raise ValueError(f"no searcher for platform: {platform}")
