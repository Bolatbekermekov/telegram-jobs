from app.domain.candidate import KIND_JOB
from app.infrastructure.search.remoteok_search import (
    RemoteOKSearcher, format_salary, job_matches, parse_remoteok_jobs,
    strip_html, to_candidate,
)

PAYLOAD = [
    {"legal": "RemoteOK disclaimer, see https://remoteok.com/api"},
    {
        "id": "1", "position": "Junior Backend Developer", "company": "Acme",
        "location": "Worldwide", "tags": ["dev", "backend", "golang"],
        "description": "<p>We use <b>Go</b> and Postgres.</p>",
        "url": "https://remoteok.com/remote-jobs/1",
        "salary_min": 50000, "salary_max": 80000,
    },
    {
        "id": "2", "position": "Senior Sales Manager", "company": "SellCo",
        "location": "US", "tags": ["sales"],
        "description": "<p>Cold calls.</p>",
        "url": "https://remoteok.com/remote-jobs/2",
        "salary_min": 0, "salary_max": 0,
    },
]


def test_parse_skips_disclaimer():
    jobs = parse_remoteok_jobs(PAYLOAD)
    assert [j["id"] for j in jobs] == ["1", "2"]


def test_job_matches_on_title_role_words():
    jobs = parse_remoteok_jobs(PAYLOAD)
    # "junior backend developer" -> role words backend/developer hit the title
    assert job_matches(jobs[0], ["junior backend developer"]) is True
    assert job_matches(jobs[0], ["backend"]) is True
    # title "Senior Sales Manager" has none of the role words
    assert job_matches(jobs[1], ["backend"]) is False
    assert job_matches(jobs[1], ["sales"]) is True


def test_job_matches_ignores_description_noise():
    # A non-dev title must NOT match even if the description mentions dev tech.
    job = {"title": "VP of Sales", "tags": ["backend", "engineer"],
           "description": "<p>Work with our backend developer team.</p>"}
    assert job_matches(job, ["junior backend developer"]) is False


def test_job_matches_drops_seniority_words():
    # "junior" alone is a seniority word -> no role word -> no match
    job = {"title": "Junior Marketing Lead", "tags": [], "description": ""}
    assert job_matches(job, ["junior"]) is False


def test_strip_html():
    assert strip_html("<p>We use <b>Go</b> and Postgres.</p>") == "We use Go and Postgres."


def test_format_salary():
    assert format_salary(50000, 80000) == "$50,000–$80,000"
    assert format_salary(0, 0) == ""


def test_to_candidate_maps_fields():
    job = parse_remoteok_jobs(PAYLOAD)[0]
    c = to_candidate(job)
    assert c.platform == "remoteok"
    assert c.kind == KIND_JOB
    assert c.title == "Junior Backend Developer"
    assert c.company == "Acme"
    assert c.salary == "$50,000–$80,000"
    assert c.location == "Worldwide"
    assert c.url == "https://remoteok.com/remote-jobs/1"
    assert c.summary == ""   # AI scorer fills this later


def test_search_filters_and_caches_description():
    s = RemoteOKSearcher()
    s._payload = lambda: PAYLOAD                      # stub network
    found = s.search(["backend"], "Worldwide", limit=10)
    assert [c.title for c in found] == ["Junior Backend Developer"]
    # describe() returns the cached, HTML-stripped description (no network call)
    assert s.describe("https://remoteok.com/remote-jobs/1") == "We use Go and Postgres."


def test_start_stop_are_noops():
    s = RemoteOKSearcher()
    s.start()
    s.stop()  # must not raise
