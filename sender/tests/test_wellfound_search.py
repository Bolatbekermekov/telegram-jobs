from app.infrastructure.search.wellfound_search import build_jobs_url, parse_job_cards


def test_build_jobs_url_contains_query():
    url = build_jobs_url("junior")
    assert "wellfound.com" in url and "junior" in url


class _FakeCard:
    def __init__(self, d):
        self._d = d

    def get_text(self, role):
        return self._d.get(role, "")

    def get_href(self):
        return self._d["href"]


def test_parse_job_cards_keeps_salary():
    cards = [_FakeCard({"title": "Junior Dev", "company": "Acme", "salary": "$40k–55k",
                        "location": "Remote", "href": "https://wellfound.com/jobs/9"})]
    out = parse_job_cards(cards, limit=10)
    c = out[0]
    assert c.platform == "wellfound" and c.kind == "job"
    assert c.salary == "$40k–55k" and c.company == "Acme"
    assert c.url == "https://wellfound.com/jobs/9"


def test_parse_job_cards_blank_salary_ok():
    cards = [_FakeCard({"title": "t", "company": "c", "salary": "",
                        "location": "Remote", "href": "https://wellfound.com/jobs/1"})]
    assert parse_job_cards(cards, limit=10)[0].salary == ""


def test_parse_respects_limit():
    cards = [_FakeCard({"title": "t", "company": "c", "salary": "", "location": "x",
                        "href": f"https://wellfound.com/jobs/{i}"}) for i in range(4)]
    assert len(parse_job_cards(cards, limit=2)) == 2
