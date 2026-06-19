from app.infrastructure.search.linkedin_search import (
    build_jobs_url, parse_job_cards, parse_people_cards,
)


def test_build_jobs_url_has_filters():
    url = build_jobs_url("junior developer", "Worldwide")
    assert "linkedin.com/jobs/search" in url
    assert "keywords=junior+developer" in url or "keywords=junior%20developer" in url
    assert "f_E=1%2C2" in url or "f_E=1,2" in url   # intern + entry
    assert "f_WT=2" in url                            # remote
    assert "f_TPR=r86400" in url                      # last 24h


class _FakeCard:
    def __init__(self, title, company, location, href):
        self._d = {"title": title, "company": company, "location": location, "href": href}

    def get_text(self, role):
        return self._d[role]

    def get_href(self):
        return self._d["href"]


def test_parse_job_cards_maps_to_candidates():
    cards = [_FakeCard("Junior Backend Engineer", "Acme", "Remote",
                       "https://www.linkedin.com/jobs/view/123")]
    out = parse_job_cards(cards, limit=10)
    assert len(out) == 1
    c = out[0]
    assert c.platform == "linkedin" and c.kind == "job"
    assert c.title == "Junior Backend Engineer" and c.company == "Acme"
    assert c.location == "Remote" and c.salary == ""
    assert c.url == "https://www.linkedin.com/jobs/view/123"


def test_parse_job_cards_respects_limit():
    cards = [_FakeCard(f"t{i}", "c", "Remote", f"https://www.linkedin.com/jobs/view/{i}")
             for i in range(5)]
    assert len(parse_job_cards(cards, limit=3)) == 3


def test_parse_people_cards_maps_profiles():
    cards = [_FakeCard("Jane Recruiter", "Tech Recruiter @ Acme", "",
                       "https://www.linkedin.com/in/jane")]
    out = parse_people_cards(cards, limit=10)
    assert out[0].kind == "profile"
    assert out[0].title == "Jane Recruiter"
    assert out[0].company == "Tech Recruiter @ Acme"
    assert out[0].url == "https://www.linkedin.com/in/jane"
