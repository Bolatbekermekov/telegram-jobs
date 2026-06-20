from app.domain.search_request import SEARCH_PLATFORMS, platforms_for
from app.infrastructure.search.registry import build_searcher


def test_every_declared_platform_is_buildable():
    # The worker builds {p: build_searcher(p) for p in SEARCH_PLATFORMS}; if any
    # declared platform had no searcher, the worker would KeyError on that request.
    for platform in SEARCH_PLATFORMS:
        assert build_searcher(platform) is not None


def test_search_platforms_includes_new_boards():
    assert "remoteok" in SEARCH_PLATFORMS
    assert "remotive" in SEARCH_PLATFORMS


def test_all_expands_to_every_platform():
    assert platforms_for("all") == ["linkedin", "wellfound", "remoteok", "remotive"]
