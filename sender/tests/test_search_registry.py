import pytest

from app.infrastructure.search.registry import build_searcher
from app.infrastructure.search.linkedin_search import LinkedInSearcher
from app.infrastructure.search.wellfound_search import WellfoundSearcher


def test_build_linkedin():
    s = build_searcher("linkedin")
    assert isinstance(s, LinkedInSearcher)


def test_build_wellfound():
    s = build_searcher("wellfound")
    assert isinstance(s, WellfoundSearcher)


def test_unknown_platform_raises():
    with pytest.raises(ValueError):
        build_searcher("telegram")


def test_wellfound_uses_cdp():
    s = build_searcher("wellfound")
    assert s.uses_cdp is True


def test_build_remoteok():
    from app.infrastructure.search.remoteok_search import RemoteOKSearcher
    assert isinstance(build_searcher("remoteok"), RemoteOKSearcher)


def test_build_remotive():
    from app.infrastructure.search.remotive_search import RemotiveSearcher
    assert isinstance(build_searcher("remotive"), RemotiveSearcher)


def test_build_hh():
    from app.infrastructure.search.hh_search import HHSearcher
    assert isinstance(build_searcher("hh"), HHSearcher)


def test_hh_gets_its_filters_from_config():
    """Настройки из .env должны доехать до searcher'а, а не осесть в конфиге.

    Ровно этого не хватало до 2026-08-27: `location` в HHSearcher.search
    принимался и не использовался, а больше фильтров и не было — hh искался
    голым текстовым запросом.
    """
    from app import config

    s = build_searcher("hh")
    assert s._work_format == config.HH_WORK_FORMAT
    assert s._areas == config.HH_AREAS
    assert s._search_period == config.HH_SEARCH_PERIOD
    assert s._pages == config.HH_PAGES
