from app.domain.search_request import (
    SearchRequest, REQ_PENDING, REQ_RUNNING, REQ_DONE, REQ_ERROR,
    per_keyword_limit, platforms_for,
)


# Бюджет платформы больше НЕ делится между ключевыми словами. Старое правило
# давало per_keyword_limit(15, 9) = max(1, 15 // 9) = 1: с девятью словами каждый
# запрос отдавал ОДНУ вакансию, и всегда одну и ту же, потому что LinkedIn
# сортирует по релевантности, а не по дате. Замер листа это и показал — 36
# кандидатов в первый день и 4–11 в каждый следующий, остальное отсеивалось как
# дубль. На самой же странице LinkedIn лежит 25 вакансий, а по одному слову
# «ai engineer» за неделю их больше восьми тысяч.

def test_one_keyword_gets_its_own_ceiling_not_a_share():
    """Девять слов больше не означают по одной вакансии на слово."""
    assert per_keyword_limit(total=120, n_keywords=9, per_keyword=25) == 25


def test_the_platform_budget_still_caps_a_single_query():
    """Брать из одного запроса больше, чем платформе нужно за весь прогон,
    незачем: лишние карточки всё равно отрежутся."""
    assert per_keyword_limit(total=10, n_keywords=9, per_keyword=25) == 10


def test_a_zero_means_no_ceiling_from_that_side():
    """Ноль — это «не задано», а не «ноль карточек». Иначе опечатка в .env
    молча выключает поиск целиком."""
    assert per_keyword_limit(total=0, n_keywords=9, per_keyword=25) == 25
    assert per_keyword_limit(total=120, n_keywords=9, per_keyword=0) == 120


def test_at_least_one_card_is_always_taken():
    assert per_keyword_limit(total=0, n_keywords=9, per_keyword=0) == 1


def test_zero_keywords_falls_back_to_the_platform_budget():
    assert per_keyword_limit(15, 0, per_keyword=25) == 15


def test_status_constants():
    assert (REQ_PENDING, REQ_RUNNING, REQ_DONE, REQ_ERROR) == (
        "pending", "running", "done", "error")


def test_platforms_for_all_expands():
    assert platforms_for("all") == [
        "linkedin", "wellfound", "remoteok", "remotive", "hh"]


def test_platforms_for_single():
    assert platforms_for("wellfound") == ["wellfound"]


def test_search_request_fields():
    r = SearchRequest(id="3", platform="all", status=REQ_PENDING)
    assert r.id == "3" and r.platform == "all" and r.status == "pending"
