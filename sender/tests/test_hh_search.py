import pytest

from app.infrastructure.search.hh_search import (
    HHSearcher,
    build_search_url,
    parse_hh_cards,
    valid_experience,
    valid_work_formats,
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


# --- фильтры выдачи hh -------------------------------------------------------
#
# Имена и значения параметров сняты с ЖИВОЙ выдачи 2026-08-27: фильтры ставились
# руками в интерфейсе, адрес читался после применения. Кнопка «Показать N
# вакансий» в панели фильтров даёт
#   /search/vacancy?text=python+developer&search_field=name&search_field=company_name
#   &search_field=description&work_format=REMOTE&enable_snippets=true&...
# а чип «Регион» —
#   /search/vacancy?text=python+developer&area=40&search_field=...&L_save_area=true
# Значения регионов подтверждены подписью самого чипа: 1=Москва, 2=Санкт-
# Петербург, 40=Казахстан, 113=Россия, 159=Астана, 160=Алматы, 16=Беларусь,
# 97=Узбекистан, 1001=Другие регионы.

def test_a_bare_query_carries_no_filters():
    """Ни одного фильтра, пока их не попросили: пустой .env ничего не сужает."""
    url = build_search_url("python developer")
    assert "area=" not in url
    assert "work_format=" not in url
    assert "experience=" not in url
    assert "search_period=" not in url
    assert "order_by=" not in url


def test_the_remote_work_format_is_asked_for_when_configured():
    assert "work_format=REMOTE" in build_search_url("dev", work_format=["REMOTE"])


def test_several_work_formats_are_repeated_not_joined():
    """hh складывает одноимённые параметры по ИЛИ, а не по запятой.

    Замер 2026-08-27, «python developer»: work_format=REMOTE — 1 708 вакансий,
    два параметра REMOTE и HYBRID — 2 764, а одно значение «REMOTE,HYBRID» —
    5 236, то есть столько же, сколько без фильтра: запятую hh не понимает и
    молча снимает фильтр. Регионы складываются так же: area=1 (Москва) — 2 802,
    area=2 (Санкт-Петербург) — 491, оба вместе — 3 278.
    """
    url = build_search_url("dev", work_format=["REMOTE", "HYBRID"])
    assert "work_format=REMOTE" in url and "work_format=HYBRID" in url
    assert "REMOTE%2CHYBRID" not in url and "REMOTE,HYBRID" not in url


def test_the_region_is_asked_for_when_configured():
    assert "area=40" in build_search_url("dev", areas=["40"])


def test_several_regions_are_repeated_too():
    url = build_search_url("dev", areas=["40", "113"])
    assert "area=40" in url and "area=113" in url


def test_experience_levels_are_repeated_too():
    url = build_search_url("dev", experience=["noExperience", "between1And3"])
    assert "experience=noExperience" in url and "experience=between1And3" in url


def test_the_publication_window_and_sort_order_are_asked_for_when_configured():
    """search_period — в ДНЯХ (1/3/7/30), order_by — publication_time."""
    url = build_search_url("dev", search_period=7, order_by="publication_time")
    assert "search_period=7" in url
    assert "order_by=publication_time" in url


def test_a_zero_window_means_no_window_at_all():
    """Ноль — это «за всё время», а не «за ноль дней»."""
    assert "search_period" not in build_search_url("dev", search_period=0)


# --- опечатка в .env не должна тихо снимать фильтр ---------------------------
#
# hh на неизвестное значение фильтра не ругается и пусто не отдаёт — он молча
# выбрасывает фильтр целиком. Замер 2026-08-27, «python developer»:
# work_format=REMOTE — 1 712 вакансий, work_format=remote (тот же смысл, другой
# регистр) — 5 236, ровно столько же, сколько вообще без фильтра. Так же
# отрабатывают work_format=камни, experience=junior и area=999999. То есть один
# неверный символ в .env возвращает поиск в состояние «до 2026-08-27» — с
# перекосом в московские офисы, ради которого фильтр и заводили.

def test_a_misspelled_work_format_is_dropped_not_sent():
    assert valid_work_formats(["REMOTE", "камни"]) == ["REMOTE"]


def test_work_formats_are_case_insensitive():
    assert valid_work_formats(["remote", "Hybrid"]) == ["REMOTE", "HYBRID"]


def test_a_misspelled_experience_level_is_dropped_not_sent():
    assert valid_experience(["noExperience", "junior"]) == ["noExperience"]


def test_experience_levels_are_case_insensitive():
    assert valid_experience(["NOEXPERIENCE", "Between1And3"]) == \
        ["noExperience", "between1And3"]


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


def test_each_keyword_gets_its_own_ceiling(monkeypatch):
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

    # Бюджет платформы больше не делится между словами: у каждого запроса свой
    # потолок. Прежнее правило при девяти словах давало по ОДНОЙ вакансии на
    # слово — и всегда одной и той же.
    s._per_keyword = 3
    got = s.search(["a", "b"], location="", limit=100)
    from_a = [c for c in got if "/vacancy/a-" in c.url]
    from_b = [c for c in got if "/vacancy/b-" in c.url]
    assert len(from_a) == 3
    assert len(from_b) == 3


class _RecordingPage:
    """Запоминает каждый запрошенный адрес; выдача всегда «пустая»."""

    url = ""

    def __init__(self):
        self.visited = []

    def goto(self, url, **kwargs):
        self.visited.append(url)
        self.url = url

    def wait_for_selector(self, sel, **kwargs):
        pass


def _searcher_with(page, **kwargs):
    s = HHSearcher("hh.json", headless=True, **kwargs)
    s._page = page
    s._vacancy_cards = lambda: []
    return s


def test_the_searcher_puts_its_filters_into_every_request():
    """Настройки доезжают до адреса, а не остаются лежать в конфиге.

    До 2026-08-27 hh искался голым текстовым запросом: ни региона, ни формата
    работы. Замер того дня — 30 лидов, почти все Москва и Санкт-Петербург, при
    том что владелец аккаунта живёт в Астане и ищет удалённую работу.
    """
    page = _RecordingPage()
    s = _searcher_with(page, areas=["40", "113"], work_format=["REMOTE"],
                       experience=["noExperience"], search_period=7,
                       order_by="publication_time")
    s.search(["python developer"], location="", limit=10)
    assert page.visited
    for url in page.visited:
        assert "area=40" in url and "area=113" in url
        assert "work_format=REMOTE" in url
        assert "experience=noExperience" in url
        assert "search_period=7" in url
        assert "order_by=publication_time" in url


def test_without_settings_the_url_stays_what_it_was():
    """Пустой .env => прежний голый запрос. Обновление не ломает работающее."""
    page = _RecordingPage()
    s = _searcher_with(page)
    s.search(["python developer"], location="", limit=10)
    assert page.visited[0] == \
        "https://hh.ru/search/vacancy?text=python%20developer&page=0"


def test_how_many_pages_to_walk_is_a_setting_not_a_constant():
    page = _RecordingPage()
    s = _searcher_with(page, pages=4)
    s.search(["dev"], location="", limit=100)
    assert [u for u in page.visited if "page=3" in u]


def test_one_page_means_one_request_per_keyword():
    page = _RecordingPage()
    s = _searcher_with(page, pages=1)
    s.search(["dev"], location="", limit=100)
    assert len(page.visited) == 1


def test_the_generic_location_argument_is_not_used_by_hh():
    """`location` приходит из run_search строкой вида «Worldwide».

    hh адресует регионы ЧИСЛОВЫМИ id (40 = Казахстан), поэтому подставить сюда
    общую для площадок строку нельзя — у hh свой список HH_AREAS.
    """
    page = _RecordingPage()
    s = _searcher_with(page)
    s.search(["dev"], location="Worldwide", limit=10)
    assert "Worldwide" not in page.visited[0]


# --- describe: дешёвое чтение вместо браузера -------------------------------

class _DeadPage:
    """Страница, которая громко падает: браузера в этих проверках быть не должно."""

    def goto(self, *a, **k):
        raise AssertionError("браузер трогать нельзя: описание пришло по HTTP")

    def locator(self, *a, **k):
        raise AssertionError("браузер трогать нельзя: описание пришло по HTTP")


def _searcher(fetch_text):
    s = HHSearcher("session.json", fetch_text=fetch_text)
    s._page = _DeadPage()
    return s


def test_describe_reads_over_http_and_never_opens_the_browser():
    asked = []

    def fetch(url):
        asked.append(url)
        return "Frontend-разработчик. Удалённо, React."

    text = _searcher(fetch).describe("https://hh.ru/vacancy/136593041")

    assert text == "Frontend-разработчик. Удалённо, React."
    assert asked == ["https://hh.ru/vacancy/136593041"]


def test_describe_trims_http_text_to_the_scorer_budget():
    text = _searcher(lambda url: "я" * 9000).describe("https://hh.ru/vacancy/1")
    assert len(text) == 6000


class _LiveLocator:
    def __init__(self, text):
        self.first = self
        self._text = text

    def inner_text(self, timeout=0):
        return self._text


class _LivePage:
    def __init__(self, text):
        self._text = text
        self.visited = []

    def goto(self, url, **k):
        self.visited.append(url)

    def locator(self, selector):
        return _LiveLocator(self._text)


def test_describe_falls_back_to_the_browser_when_http_reads_nothing():
    """Переезд разметки не должен обнулять скоринг всей площадки."""
    s = HHSearcher("session.json", fetch_text=lambda url: "")
    s._page = _LivePage("  Описание со страницы  ")

    assert s.describe("https://hh.ru/vacancy/7") == "Описание со страницы"
    assert s._page.visited == ["https://hh.ru/vacancy/7"]


class _BrokenPage:
    def goto(self, *a, **k):
        raise RuntimeError("страница не открылась")


def test_describe_returns_empty_when_both_paths_fail():
    s = HHSearcher("session.json", fetch_text=lambda url: "")
    s._page = _BrokenPage()

    assert s.describe("https://hh.ru/vacancy/10") == ""
