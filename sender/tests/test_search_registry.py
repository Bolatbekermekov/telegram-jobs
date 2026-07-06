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


def test_build_wwr():
    from app.infrastructure.search.wwr_search import WWRSearcher
    assert isinstance(build_searcher("wwr"), WWRSearcher)


def test_build_hh():
    from app.infrastructure.search.hh_search import HHSearcher
    assert isinstance(build_searcher("hh"), HHSearcher)
