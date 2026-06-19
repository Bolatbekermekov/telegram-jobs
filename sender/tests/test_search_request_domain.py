from app.domain.search_request import (
    SearchRequest, REQ_PENDING, REQ_RUNNING, REQ_DONE, REQ_ERROR,
    platforms_for,
)


def test_status_constants():
    assert (REQ_PENDING, REQ_RUNNING, REQ_DONE, REQ_ERROR) == (
        "pending", "running", "done", "error")


def test_platforms_for_all_expands():
    assert platforms_for("all") == ["linkedin", "wellfound"]


def test_platforms_for_single():
    assert platforms_for("wellfound") == ["wellfound"]


def test_search_request_fields():
    r = SearchRequest(id="3", platform="all", status=REQ_PENDING)
    assert r.id == "3" and r.platform == "all" and r.status == "pending"
