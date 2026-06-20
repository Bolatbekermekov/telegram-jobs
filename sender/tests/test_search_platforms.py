from app.domain.search_request import SEARCH_PLATFORMS, platforms_for


def test_search_platforms_includes_new_boards():
    assert "remoteok" in SEARCH_PLATFORMS
    assert "remotive" in SEARCH_PLATFORMS


def test_all_expands_to_every_platform():
    assert platforms_for("all") == ["linkedin", "wellfound", "remoteok", "remotive"]
