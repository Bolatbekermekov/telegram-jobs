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
