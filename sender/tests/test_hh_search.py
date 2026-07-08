import pytest

from app.infrastructure.search.hh_search import (
    HHSearcher,
    build_search_url,
    parse_hh_cards,
)


def test_search_raises_when_redirected_to_login():
    s = HHSearcher("hh.json", headless=True)

    class _LoginPage:
        url = "https://hh.ru/account/login?backurl=%2Fsearch%2Fvacancy"

        def goto(self, url, **kw):
            pass

    s._page = _LoginPage()
    with pytest.raises(RuntimeError, match="login_hh"):
        s.search(["python"], "", 5)


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


def test_search_splits_limit_across_keywords(monkeypatch):
    s = HHSearcher("hh.json", headless=True)
    state = {"query": ""}

    class _FakePage:
        url = ""  # stays on the search page (no login redirect)

        def goto(self, url, **kwargs):
            # extract the query from ...?text=<q>&page=N
            state["query"] = url.split("text=")[1].split("&")[0]
            self.url = url

        def wait_for_selector(self, sel, **kwargs):
            pass

    s._page = _FakePage()
    # 10 distinct cards per page, URLs encode the current query in the path
    # (normalize_url drops query strings, so the keyword must live in the path)
    monkeypatch.setattr(s, "_vacancy_cards", lambda: [
        _Card(f"Dev {state['query']} {i}",
              f"https://hh.ru/vacancy/{state['query']}-{i}")
        for i in range(10)
    ])

    got = s.search(["a", "b"], location="", limit=4)
    assert len(got) == 4
    from_a = [c for c in got if "/vacancy/a-" in c.url]
    from_b = [c for c in got if "/vacancy/b-" in c.url]
    assert len(from_a) == 2
    assert len(from_b) == 2
