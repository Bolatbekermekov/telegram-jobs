from app.domain.candidate import KIND_JOB
from app.infrastructure.search.remotive_search import (
    RemotiveSearcher, parse_remotive_jobs, strip_html, to_candidate,
)

PAYLOAD = {
    "job-count": 2,
    "jobs": [
        {
            "id": 1,
            "url": "https://remotive.com/remote-jobs/dev/junior-backend-1",
            "title": "Junior Backend Developer", "company_name": "Acme",
            "category": "Software Development", "tags": ["golang", "postgres"],
            "salary": "$50k - $80k", "candidate_required_location": "Worldwide",
            "description": "<p>We use <b>Go</b> and Postgres.</p>",
        },
        {
            "id": 2,
            "url": "https://remotive.com/remote-jobs/dev/frontend-2",
            "title": "Frontend Engineer", "company_name": "SellCo",
            "category": "Software Development", "tags": ["react"],
            "salary": "", "candidate_required_location": "USA Only",
            "description": "<p>React work.</p>",
        },
    ],
}


def test_parse_returns_jobs_list():
    jobs = parse_remotive_jobs(PAYLOAD)
    assert [j["id"] for j in jobs] == [1, 2]


def test_parse_handles_missing_jobs_key():
    assert parse_remotive_jobs({}) == []


def test_strip_html():
    assert strip_html("<p>We use <b>Go</b> and Postgres.</p>") == "We use Go and Postgres."


def test_to_candidate_maps_fields():
    job = parse_remotive_jobs(PAYLOAD)[0]
    c = to_candidate(job)
    assert c.platform == "remotive"
    assert c.kind == KIND_JOB
    assert c.title == "Junior Backend Developer"
    assert c.company == "Acme"
    assert c.salary == "$50k - $80k"
    assert c.location == "Worldwide"
    assert c.url == "https://remotive.com/remote-jobs/dev/junior-backend-1"
    assert c.summary == ""   # AI scorer fills this later


def test_search_title_filters_dedups_and_caches_description():
    s = RemotiveSearcher()
    s._payload = lambda: PAYLOAD                    # stub the cached feed
    found = s.search(["backend developer", "frontend engineer"], "Worldwide", limit=10)
    assert sorted(c.title for c in found) == ["Frontend Engineer", "Junior Backend Developer"]
    # describe() returns the cached, HTML-stripped description (no network call)
    assert s.describe("https://remotive.com/remote-jobs/dev/junior-backend-1") == \
        "We use Go and Postgres."


def test_search_drops_non_matching_titles():
    payload = {"jobs": [
        {"id": 9, "url": "https://remotive.com/remote-jobs/x/office-assistant-9",
         "title": "Office Assistant", "company_name": "Acme",
         "candidate_required_location": "Worldwide", "salary": "",
         "description": "<p>Filing.</p>"},
    ]}
    s = RemotiveSearcher()
    s._payload = lambda: payload
    assert s.search(["backend developer"], "Worldwide", limit=10) == []


def test_search_survives_payload_error():
    s = RemotiveSearcher()

    def boom():
        raise RuntimeError("503 Service Unavailable")

    s._payload = boom
    assert s.search(["backend"], "Worldwide", limit=5) == []


def test_start_stop_are_noops():
    s = RemotiveSearcher()
    s.start()
    s.stop()  # must not raise
