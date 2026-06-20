from app import config


def test_search_defaults_present():
    # SEARCH_KEYWORDS is user config (set in .env); just require a non-empty list.
    assert isinstance(config.SEARCH_KEYWORDS, list) and config.SEARCH_KEYWORDS
    assert config.SEARCH_LOCATION == "Worldwide"
    assert config.SEARCH_LIMIT_PER_PLATFORM == 15
    assert config.SHOW_BATCH == 7
    assert config.WORKER_POLL_SECONDS == 60
    assert config.HEARTBEAT_STALE_SECONDS == 180
    assert config.LINKEDIN_PEOPLE_ENABLED is False
    assert config.PACING_MIN_SECONDS < config.PACING_MAX_SECONDS
