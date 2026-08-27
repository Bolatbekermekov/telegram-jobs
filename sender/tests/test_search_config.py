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


# --- фильтры hh --------------------------------------------------------------
#
# Замер живой выдачи 2026-08-27 по тем же 14 словам, что лежат в SEARCH_KEYWORDS
# (сумма по всем словам): без фильтра 16 134 вакансии, с удалёнкой 6 005,
# «удалёнка + Казахстан» 275, «удалёнка + нет опыта/1–3 года» 1 820. Отсюда и
# значения по умолчанию: режем по формату работы, но не по региону и не по
# уровню — там выдача садится ниже потолка SEARCH_PER_KEYWORD=25 на слово.

def test_hh_filters_have_defaults():
    assert config.HH_WORK_FORMAT == ["REMOTE"]
    assert config.HH_AREAS == []        # регион не сужаем: hh складывает его с
    assert config.HH_EXPERIENCE == []   # форматом по И, и остаётся 3–56 на слово
    assert config.HH_SEARCH_PERIOD == 7
    assert config.HH_ORDER_BY == ""     # по релевантности, умолчание самого hh
    assert config.HH_PAGES == 2
