from app.domain.candidate import Candidate, STATUS_PENDING
from app.infrastructure.candidates_repo import candidate_to_row, should_add


def _cand(url, platform="linkedin"):
    return Candidate(platform=platform, kind="job", url=url, title="t", company="c",
                     salary="", location="Remote", summary="s")


def test_candidate_to_row_positional():
    row = candidate_to_row(_cand("https://x/1"), row_id=4, now="2026-06-15 10:00")
    # id, Платформа, Тип, URL, Title, Company, Salary, Location, Summary, Статус, Дата
    assert row == [4, "linkedin", "job", "https://x/1", "t", "c", "", "Remote", "s",
                   STATUS_PENDING, "2026-06-15 10:00"]


def test_should_add_true_when_new_and_under_cap():
    assert should_add(_cand("https://x/1"), seen_keys=set(), platform_pending=0, cap=15)


def test_should_add_false_when_url_seen():
    seen = {"https://x/1"}
    assert not should_add(_cand("https://x/1/?ref=a"), seen_keys=seen,
                          platform_pending=0, cap=15)


def test_should_add_false_when_cap_reached():
    assert not should_add(_cand("https://x/2"), seen_keys=set(),
                          platform_pending=15, cap=15)
