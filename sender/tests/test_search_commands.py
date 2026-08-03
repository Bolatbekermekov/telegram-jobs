from app.application.search_commands import platforms_arg


def test_search_token_means_all_platforms():
    assert platforms_arg("search") == [
        "linkedin", "wellfound", "remoteok", "remotive", "hh"]


def test_per_platform_tokens():
    assert platforms_arg("search_linkedin") == ["linkedin"]
    assert platforms_arg("search_wellfound") == ["wellfound"]
    assert platforms_arg("search_remoteok") == ["remoteok"]
    assert platforms_arg("search_remotive") == ["remotive"]


def test_search_hh_token_maps_to_hh():
    assert platforms_arg("search_hh") == ["hh"]
