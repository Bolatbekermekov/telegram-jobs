from app.domain.candidate import (
    Candidate, CANDIDATE_COLUMNS, normalize_url, linkedin_action_for_url,
)


def test_candidate_columns_order():
    assert CANDIDATE_COLUMNS == [
        "id", "Платформа", "Тип", "URL", "Title", "Company",
        "Salary", "Location", "Summary", "Статус", "Дата",
    ]


def test_normalize_url_lowercases_host_strips_query_fragment_slash():
    a = normalize_url("HTTPS://www.LinkedIn.com/jobs/view/123/?ref=abc#top")
    b = normalize_url("https://www.linkedin.com/jobs/view/123")
    assert a == b == "https://www.linkedin.com/jobs/view/123"


def test_normalize_url_handles_trailing_slash_only():
    assert normalize_url("https://wellfound.com/jobs/9/") == "https://wellfound.com/jobs/9"


def test_linkedin_action_for_url():
    assert linkedin_action_for_url("https://www.linkedin.com/jobs/view/1") == "easy_apply"
    assert linkedin_action_for_url("https://www.linkedin.com/in/jane-doe") == "dm"


def test_candidate_is_a_dataclass_with_fields():
    c = Candidate(platform="linkedin", kind="job", url="u", title="t",
                  company="c", salary="", location="Remote", summary="s")
    assert c.platform == "linkedin" and c.kind == "job" and c.salary == ""
