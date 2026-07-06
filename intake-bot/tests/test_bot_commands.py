from app.domain.bot_commands import command_to_search_platform


def test_start_search_means_all():
    assert command_to_search_platform("/start_search") == "all"


def test_per_platform_commands():
    assert command_to_search_platform("/search_linkedin") == "linkedin"
    assert command_to_search_platform("/search_wellfound") == "wellfound"


def test_non_search_command_returns_none():
    assert command_to_search_platform("/show_vacancies") is None
    assert command_to_search_platform("just some vacancy text") is None


def test_search_hh_command():
    assert command_to_search_platform("/search_hh") == "hh"
