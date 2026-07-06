import pytest

from app.infrastructure.search.hh_search import (
    HHSearcher,
    build_search_url,
    parse_hh_cards,
)


class _Card:
    def __init__(self, title, href, company="Acme", salary="", location="Almaty"):
        self._d = {"title": title, "company": company,
                   "salary": salary, "location": location}
        self._href = href

    def get_text(self, role):
        return self._d[role]

    def get_href(self):
        return self._href


def test_build_search_url_quotes_query_and_page():
    assert build_search_url("junior python", 1) == \
        "https://hh.ru/search/vacancy?text=junior%20python&page=1"


def test_parse_maps_cards_to_candidates():
    cards = [_Card("Junior Python", "https://hh.ru/vacancy/1?from=serp")]
    got = parse_hh_cards(cards, limit=10)
    assert len(got) == 1
    c = got[0]
    assert c.platform == "hh"
    assert c.kind == "job"
    assert c.title == "Junior Python"
    assert c.company == "Acme"
    assert c.url == "https://hh.ru/vacancy/1?from=serp"


def test_parse_skips_cards_without_title_or_url():
    cards = [_Card("", "https://hh.ru/vacancy/1"), _Card("Dev", "")]
    assert parse_hh_cards(cards, limit=10) == []


def test_parse_respects_limit():
    cards = [_Card(f"Dev {i}", f"https://hh.ru/vacancy/{i}") for i in range(5)]
    assert len(parse_hh_cards(cards, limit=3)) == 3


def test_searcher_metadata():
    s = HHSearcher("hh.json", headless=True)
    assert s.name == "hh"


def test_searcher_start_raises_without_state(tmp_path):
    s = HHSearcher(str(tmp_path / "missing.json"), headless=True)
    with pytest.raises(RuntimeError, match="login_hh"):
        s.start()
