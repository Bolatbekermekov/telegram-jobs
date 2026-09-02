"""Build the right searcher for a platform (mirrors channels/registry.py)."""
import time

from app import config
from app.infrastructure.search.hh_search import HHSearcher
from app.infrastructure.search.linkedin_search import LinkedInSearcher
from app.infrastructure.search.remocate_search import RemocateSearcher
from app.infrastructure.search.remoteok_search import RemoteOKSearcher
from app.infrastructure.search.remotive_search import RemotiveSearcher
from app.infrastructure.search.wellfound_search import WellfoundSearcher


def build_searcher(platform: str):
    if platform == "linkedin":
        return LinkedInSearcher(
            config.LINKEDIN_STATE_PATH,
            headless=config.BROWSER_HEADLESS,
            people_enabled=config.LINKEDIN_PEOPLE_ENABLED,
            experience=config.LINKEDIN_EXPERIENCE,
            posted_within=config.LINKEDIN_POSTED_WITHIN,
            workplace=config.LINKEDIN_WORKPLACE,
            per_keyword=config.LINKEDIN_PER_KEYWORD,
            pages=config.LINKEDIN_PAGES,
            locations=config.SEARCH_LOCATIONS,
            # Сдвиг стартового запроса меняется каждый час: бюджет обрывает
            # обход, и без ротации опрашивались бы вечно одни и те же первые
            # пары «слово + страна».
            rotate_by=int(time.time() // 3600),
        )
    if platform == "wellfound":
        return WellfoundSearcher(
            config.WELLFOUND_STATE_PATH,
            headless=config.BROWSER_HEADLESS,
            cdp_url=config.WELLFOUND_CDP_URL,
            per_keyword=config.WELLFOUND_PER_KEYWORD,
            remote_only=config.WELLFOUND_REMOTE_ONLY,
            pages=config.WELLFOUND_PAGES,
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
    if platform == "remocate":
        # Имя площадки то же, что у канала отправки: и лид, и его отправку, и
        # паузу зовут одним словом `remocate` (см. channels/registry.py).
        return RemocateSearcher(
            feed_url=config.REMOCATE_FEED_URL,
            pages=config.REMOCATE_PAGES,
            # Второй проход — по главной: разделы не пересекаются, а у 102
            # вакансий категории нет вовсе, и видны они только там.
            home_pages=config.REMOCATE_HOME_PAGES,
            qa_url=config.REMOCATE_QA_URL,
            qa_pages=config.REMOCATE_QA_PAGES,
            user_agent=config.HTTP_USER_AGENT,
            timeout=config.HTTP_TIMEOUT_SECONDS,
        )
    if platform == "hh":
        return HHSearcher(
            config.HH_STATE_PATH, headless=config.BROWSER_HEADLESS,
            per_keyword=config.SEARCH_PER_KEYWORD,
            # Регион у hh свой (числовые id), а не общий SEARCH_LOCATION:
            # «Worldwide» hh не понимает — см. app/config.py.
            areas=config.HH_AREAS,
            work_format=config.HH_WORK_FORMAT,
            experience=config.HH_EXPERIENCE,
            search_period=config.HH_SEARCH_PERIOD,
            order_by=config.HH_ORDER_BY,
            pages=config.HH_PAGES,
        )
    raise ValueError(f"no searcher for platform: {platform}")
