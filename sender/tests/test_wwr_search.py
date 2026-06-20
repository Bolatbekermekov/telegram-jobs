from app.domain.candidate import KIND_JOB
from app.infrastructure.search.wwr_search import build_category_url, parse_wwr_cards


class _Card:
    def __init__(self, title, company, location, href):
        self._d = {"title": title, "company": company, "location": location}
        self._href = href

    def get_text(self, role):
        return self._d[role]

    def get_href(self):
        return self._href


def test_build_category_url():
    assert build_category_url("remote-back-end-programming-jobs") == \
        "https://weworkremotely.com/categories/remote-back-end-programming-jobs"


def test_parse_filters_by_title_and_maps_fields():
    cards = [
        _Card("Senior Backend Engineer", "Close", "USA",
              "https://weworkremotely.com/remote-jobs/x-1"),
        _Card("Office Manager", "Acme", "Worldwide",
              "https://weworkremotely.com/remote-jobs/x-2"),
        _Card("Frontend Developer", "SellCo", "Anywhere",
              "https://weworkremotely.com/remote-jobs/x-3"),
    ]
    out = parse_wwr_cards(cards, ["backend developer", "frontend developer"], limit=10)
    assert [c.title for c in out] == ["Senior Backend Engineer", "Frontend Developer"]
    first = out[0]
    assert first.platform == "wwr"
    assert first.kind == KIND_JOB
    assert first.company == "Close"
    assert first.location == "USA"
    assert first.url == "https://weworkremotely.com/remote-jobs/x-1"
    assert first.summary == ""


def test_parse_respects_limit():
    cards = [_Card(f"Backend Developer {i}", "C", "WW",
                   f"https://weworkremotely.com/remote-jobs/x-{i}") for i in range(5)]
    out = parse_wwr_cards(cards, ["backend"], limit=2)
    assert len(out) == 2
