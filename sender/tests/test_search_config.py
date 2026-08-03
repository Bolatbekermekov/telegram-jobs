from app import config


def test_search_defaults_present():
    # SEARCH_KEYWORDS is user config (set in .env); just require a non-empty list.
    assert isinstance(config.SEARCH_KEYWORDS, list) and config.SEARCH_KEYWORDS
    assert config.SEARCH_LOCATION == "Worldwide"
    assert config.SEARCH_LIMIT_PER_PLATFORM == 250
    # Предохранитель на прогон, а не рабочий потолок: реально
    # ограничивает MATCH_MAX_JOBS. И он больше НЕ управляет длиной
    # очереди человеку — за неё отвечает CANDIDATES_PENDING_CAP.
    assert config.CANDIDATES_PENDING_CAP == 60
    assert config.SEARCH_PER_KEYWORD == 25
    assert config.MATCH_MAX_JOBS == 30
    assert config.LINKEDIN_WORKPLACE == ""   # любой формат работы
    assert config.SHOW_BATCH == 7
    assert config.WORKER_POLL_SECONDS == 60
    assert config.HEARTBEAT_STALE_SECONDS == 180
    assert config.LINKEDIN_PEOPLE_ENABLED is False
    assert config.PACING_MIN_SECONDS < config.PACING_MAX_SECONDS
