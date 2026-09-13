"""Indeed не одной страной: страновые сайты и спонсорство визы.

Живой замер 2026-09-13 в Chrome Indeed, первая страница выдачи, карточек:

    www.indeed.com  «ai engineer», Remote                17
    ae.indeed.com   «ai engineer»                        16
    uk.indeed.com   «ai engineer "visa sponsorship"»     16
    de.indeed.com   «ai engineer "visa sponsorship"»     16
    ca.indeed.com   «ai engineer "visa sponsorship"»      8
    nl.indeed.com   «ai engineer "visa sponsorship"»      2

Поиск ходил только на www.indeed.com с «Remote», а это американская удалёнка:
в тексте таких вакансий «must be authorized to work in the United States», и
кандидату из Казахстана они закрыты. Профиль же прямо допускает переезд, если
работодатель спонсирует визу, — ровно то, что лежит на страновых сайтах. Адрес
выдачи был прибит к `https://www.indeed.com`, поэтому туда поиск не доходил.

Отклик на такие вакансии чинить не нужно, проверено по коду: канал открывает
ПОЛНУЮ ссылку лида и уходит на `/rc/clk` относительно неё, а `left_indeed` уже
считает страновые поддомены площадкой.
"""
import pytest

from app.infrastructure.search.indeed_search import (
    IndeedSearcher, IndeedSite, build_jobs_url, parse_indeed_sites,
)


class _Page:
    """Выдача по хосту: на каждый сайт свой набор строк; запоминает посещённое."""

    def __init__(self, rows_by_host=None, default_rows=None):
        self._rows_by_host = rows_by_host or {}
        self._default = default_rows if default_rows is not None else []
        self.visited = []
        self.url = ""

    def goto(self, url, **kw):
        self.visited.append(url)
        self.url = url

    def wait_for_selector(self, selector, timeout=None, state=None):
        pass

    def evaluate(self, script):
        host = self.visited[-1].split("//")[1].split("/")[0]
        return self._rows_by_host.get(host, self._default)


class _ChallengeAfter(_Page):
    """Первые `ok` загрузок — выдача, дальше — проверка вместо неё."""

    def __init__(self, ok, rows):
        super().__init__(default_rows=rows)
        self._ok = ok

    def _blocked(self):
        return len(self.visited) > self._ok

    def wait_for_selector(self, selector, timeout=None, state=None):
        if self._blocked():
            raise TimeoutError("no cards")

    def evaluate(self, script):
        return 0 if self._blocked() else super().evaluate(script)

    def title(self):
        return "Just a moment..." if self._blocked() else "Jobs"

    def locator(self, selector):
        text = "Verify you are human" if self._blocked() else ""

        class _Loc:
            @property
            def first(self_inner):
                return self_inner

            def inner_text(self_inner, timeout=None):
                return text

        return _Loc()


def _row(jk, host="www.indeed.com"):
    return {"title": "AI Engineer", "company": "Pulsora", "location": "Remote",
            "href": f"https://{host}/viewjob?jk={jk}"}


def _searcher(page, **kw):
    kw.setdefault("sleep", lambda seconds: None)   # иначе тесты спят по-настоящему
    s = IndeedSearcher(cdp_url="http://127.0.0.1:9226", **kw)
    s._page = page
    return s


def _host(url):
    return url.split("//")[1].split("/")[0]


# --- адрес выдачи -------------------------------------------------------------

def test_the_url_goes_to_the_site_it_is_given():
    url = build_jobs_url("ai engineer", "", page=1, host="uk.indeed.com",
                         suffix='"visa sponsorship"')
    assert url.startswith("https://uk.indeed.com/jobs?")
    assert "q=ai+engineer+%22visa+sponsorship%22" in url
    assert "l=" not in url


def test_without_a_site_the_url_stays_where_it_was():
    assert build_jobs_url("ai engineer", "Remote", page=1).startswith(
        "https://www.indeed.com/jobs?q=ai+engineer&l=Remote")


# --- настройка ----------------------------------------------------------------

def test_sites_are_read_from_one_line_of_config():
    sites = parse_indeed_sites(
        'www.indeed.com|Remote| ; ae.indeed.com ; uk.indeed.com||"visa sponsorship"')
    assert sites == [
        IndeedSite("www.indeed.com", "Remote", ""),
        IndeedSite("ae.indeed.com", "", ""),
        IndeedSite("uk.indeed.com", "", '"visa sponsorship"'),
    ]


def test_an_empty_setting_means_no_sites_of_its_own():
    assert parse_indeed_sites("") == []
    assert parse_indeed_sites("  ;  ") == []


def test_a_host_that_is_not_indeed_is_refused_loudly():
    """Адрес открывается в НАСТОЯЩЕМ Chrome человека, под его сессией: опечатка
    в .env не вправе увести этот браузер на чужой сайт. И молча выпасть из обхода
    она не вправе тоже — прогон тихо стал бы меньше задуманного."""
    with pytest.raises(ValueError, match="indeed.com.evil.example"):
        parse_indeed_sites("indeed.com.evil.example|Remote|")


# --- обход ----------------------------------------------------------------------

def test_every_site_is_searched_with_its_own_location_and_suffix():
    page = _Page(default_rows=[_row("1111111111111111")])
    sites = [IndeedSite("www.indeed.com", "Remote", ""),
             IndeedSite("uk.indeed.com", "", '"visa sponsorship"')]
    _searcher(page, sites=sites, pages=1).search(["ai engineer"], "", 10)
    assert page.visited[0].startswith("https://www.indeed.com/jobs?q=ai+engineer&l=Remote")
    assert page.visited[1].startswith(
        "https://uk.indeed.com/jobs?q=ai+engineer+%22visa+sponsorship%22")


def test_each_site_gets_its_first_page_before_any_site_gets_a_second():
    """Бюджет обрывает перебор. При обходе «сайт снаружи» первая страна съела бы
    его целиком, и до спонсорства визы очередь не доходила бы никогда."""
    page = _Page(default_rows=[_row("2222222222222222")])
    sites = [IndeedSite("www.indeed.com", "Remote", ""), IndeedSite("ae.indeed.com", "", "")]
    _searcher(page, sites=sites, pages=2).search(["ai engineer"], "", 50)
    order = [(_host(u), u.split("start=")[1].split("&")[0]) for u in page.visited]
    assert order == [("www.indeed.com", "0"), ("ae.indeed.com", "0"),
                     ("www.indeed.com", "10"), ("ae.indeed.com", "10")]


def test_a_keyword_empty_on_one_site_is_still_asked_on_another():
    page = _Page(rows_by_host={"ae.indeed.com": [_row("3333333333333333", "ae.indeed.com")]})
    sites = [IndeedSite("www.indeed.com", "Remote", ""), IndeedSite("ae.indeed.com", "", "")]
    found = _searcher(page, sites=sites, pages=2).search(["ai engineer"], "", 50)
    assert [_host(u) for u in page.visited] == ["www.indeed.com", "ae.indeed.com", "ae.indeed.com"]
    assert [c.url for c in found] == ["https://ae.indeed.com/viewjob?jk=3333333333333333"]


def test_without_sites_the_searcher_walks_exactly_as_before():
    page = _Page(default_rows=[_row("6666666666666666")])
    _searcher(page, pages=1, location="Remote").search(["ai engineer"], "", 10)
    assert page.visited == ["https://www.indeed.com/jobs?q=ai+engineer&l=Remote&start=0"]


# --- проверка вместо страницы ---------------------------------------------------

def test_a_challenge_midway_keeps_what_was_already_found(capsys):
    """Живьём 2026-09-12 шесть запросов подряд уже давали «Security Check». Обход
    нескольких стран делает их десятками, и проверка на сороковом запросе стёрла
    бы собранное на первых тридцати девяти: `run_search` ловит исключение
    площадки целиком и в таблицу не пишет ничего. Найденное отдаём, об обрыве
    говорим вслух."""
    page = _ChallengeAfter(ok=1, rows=[_row("4444444444444444")])
    sites = [IndeedSite("www.indeed.com", "Remote", ""), IndeedSite("ae.indeed.com", "", "")]
    found = _searcher(page, sites=sites, pages=1).search(["ai engineer"], "", 50)
    assert [c.url for c in found] == ["https://www.indeed.com/viewjob?jk=4444444444444444"]
    assert "проверк" in capsys.readouterr().out.lower()


def test_a_challenge_instead_of_a_vacancy_is_not_handed_to_the_scorer():
    """Страница проверки — не описание вакансии. Отдай её скореру, и он честно
    поставит низкий балл, а память отказников запомнит вакансию НАВСЕГДА и
    больше её не оценит. Исключение же `score_and_filter` пропускает, не
    записывая вердикта."""
    page = _ChallengeAfter(ok=0, rows=[])
    with pytest.raises(RuntimeError):
        _searcher(page).describe("https://uk.indeed.com/viewjob?jk=5555555555555555")


# --- реестр ---------------------------------------------------------------------

def test_the_registry_passes_the_configured_sites(monkeypatch):
    from app import config
    from app.infrastructure.search.registry import build_searcher
    monkeypatch.setattr(config, "INDEED_SITES", 'ae.indeed.com||;uk.indeed.com||"visa sponsorship"')
    assert [s.host for s in build_searcher("indeed")._sites] == ["ae.indeed.com", "uk.indeed.com"]


def test_without_configured_sites_indeed_searches_where_it_always_did(monkeypatch):
    from app import config
    from app.infrastructure.search.registry import build_searcher
    monkeypatch.setattr(config, "INDEED_SITES", "")
    assert build_searcher("indeed")._sites == [
        IndeedSite("www.indeed.com", config.INDEED_LOCATION, "")]
