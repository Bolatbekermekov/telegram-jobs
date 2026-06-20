from app.application.search_commands import platforms_arg


def test_search_token_means_all_platforms():
    assert platforms_arg("search") == ["linkedin", "wellfound"]


def test_per_platform_tokens():
    assert platforms_arg("search_linkedin") == ["linkedin"]
    assert platforms_arg("search_wellfound") == ["wellfound"]
