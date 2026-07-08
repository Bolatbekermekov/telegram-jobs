from app.domain.search_request import (
    SearchRequest, REQ_PENDING, REQ_RUNNING, REQ_DONE, REQ_ERROR,
    per_keyword_limit, platforms_for,
)


def test_per_keyword_limit_splits_total_across_keywords():
    assert per_keyword_limit(15, 5) == 3
    assert per_keyword_limit(15, 6) == 2   # floor


def test_per_keyword_limit_is_at_least_one():
    assert per_keyword_limit(3, 10) == 1


def test_per_keyword_limit_handles_zero_keywords():
    assert per_keyword_limit(15, 0) == 15


def test_status_constants():
    assert (REQ_PENDING, REQ_RUNNING, REQ_DONE, REQ_ERROR) == (
        "pending", "running", "done", "error")


def test_platforms_for_all_expands():
    assert platforms_for("all") == [
        "linkedin", "wellfound", "remoteok", "remotive", "wwr", "hh"]


def test_platforms_for_single():
    assert platforms_for("wellfound") == ["wellfound"]


def test_search_request_fields():
    r = SearchRequest(id="3", platform="all", status=REQ_PENDING)
    assert r.id == "3" and r.platform == "all" and r.status == "pending"
