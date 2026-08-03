from app.infrastructure.search.linkedin_search import (
    build_jobs_url, parse_job_cards, parse_people_cards,
)


def test_build_jobs_url_has_filters():
    url = build_jobs_url("junior developer", "Worldwide")
    assert "linkedin.com/jobs/search" in url
    assert "keywords=junior+developer" in url or "keywords=junior%20developer" in url
    assert "f_E=1%2C2%2C3" in url                     # intern + junior + junior+
    assert "f_TPR=r604800" in url                     # last 7 days


# --- формат работы: фильтр, а не константа ----------------------------------
#
# f_WT=2 (только удалёнка) был вшит в код и не выключался ничем. Замер живого
# LinkedIn 2026-08-03 по одному слову за неделю: «python developer» — 1000+
# удалённых против 3000+ всего, «ai engineer» — 2000+ против 8000+. То есть
# фильтр съедал 60–75% пула, и ровно тот, что подходит человеку, готовому к
# релокации.

def test_by_default_no_workplace_filter_is_applied():
    assert "f_WT" not in build_jobs_url("go developer", "Germany")


def test_a_workplace_filter_is_applied_when_asked():
    assert "f_WT=2" in build_jobs_url("go developer", "Germany", workplace="2")


# --- пагинация ---------------------------------------------------------------

def test_the_first_page_carries_no_offset():
    assert "start=" not in build_jobs_url("go developer", "Germany")


def test_a_later_page_is_addressed_by_offset():
    """LinkedIn отдаёт по 25 вакансий на страницу, следующие — через start."""
    assert "start=25" in build_jobs_url("go developer", "Germany", start=25)


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


# --- перебор запросов --------------------------------------------------------

class _FakePage:
    def __init__(self):
        self.urls = []

    def goto(self, url, wait_until=None, timeout=None):
        self.urls.append(url)

    def wait_for_timeout(self, ms):
        pass


def _searcher(page, cards_per_page=25, **kw):
    from app.infrastructure.search.linkedin_search import LinkedInSearcher
    s = LinkedInSearcher("state.json", **kw)
    s._page = page
    counter = {"n": 0}

    def fake_cards():
        out = []
        for _ in range(cards_per_page):
            counter["n"] += 1
            i = counter["n"]
            out.append(_FakeCard(f"Job {i}", "Acme", "Remote",
                                 f"https://www.linkedin.com/jobs/view/{i}"))
        return out

    s._job_cards = fake_cards
    return s


def test_every_keyword_is_searched_in_every_location():
    """Одна локация на всё была вторым по цене ограничением: UAE, Турция и
    страны EU не искались никогда."""
    page = _FakePage()
    s = _searcher(page, locations=["Germany", "Turkey"], per_keyword=5)
    s.search(["go developer", "qa engineer"], "Worldwide", limit=1000)

    assert len(page.urls) == 4
    assert sum("location=Germany" in u for u in page.urls) == 2
    assert sum("location=Turkey" in u for u in page.urls) == 2


def test_the_location_argument_is_used_when_no_list_is_configured():
    page = _FakePage()
    s = _searcher(page, per_keyword=5)
    s.search(["go developer"], "Netherlands", limit=100)

    assert len(page.urls) == 1
    assert "location=Netherlands" in page.urls[0]


def test_a_keyword_yields_its_own_ceiling_not_a_share_of_the_budget():
    """Ровно та поломка: 9 слов при бюджете 15 давали по одной вакансии."""
    page = _FakePage()
    s = _searcher(page, per_keyword=25)
    found = s.search(["a", "b", "c", "d", "e", "f", "g", "h", "i"],
                     "Worldwide", limit=1000)

    assert len(found) == 9 * 25


def test_the_platform_budget_stops_the_walk_early():
    """Набрали сколько нужно — дальше не ходим: каждая страница это лишняя
    загрузка и лишний риск упереться в лимиты LinkedIn."""
    page = _FakePage()
    s = _searcher(page, per_keyword=25)
    found = s.search(["a", "b", "c", "d"], "Worldwide", limit=30)

    assert len(found) == 30
    assert len(page.urls) == 2          # третий запрос уже не нужен


def test_every_keyword_gets_its_first_page_before_anyone_gets_a_second():
    """Иначе первое слово съедает весь бюджет платформы и до QA с AI очередь
    не доходит вовсе — ровно от этого и защищала старая делёжка бюджета.
    Порядок обхода: страница -> локация -> ключевое слово."""
    page = _FakePage()
    s = _searcher(page, per_keyword=25, pages=2)
    s.search(["go", "qa", "ai"], "Germany", limit=1000)

    first_pass = page.urls[:3]
    assert all("start=" not in u for u in first_pass)
    assert {"go", "qa", "ai"} == {u.split("keywords=")[1].split("&")[0] for u in first_pass}
    assert "start=25" in page.urls[3]


def test_an_exhausted_query_is_not_asked_for_a_second_page():
    """Пустая страница значит, что по этой паре слово+локация вакансии
    кончились. Ходить за следующей — лишняя загрузка и лишний риск."""
    page = _FakePage()
    s = _searcher(page, cards_per_page=0, per_keyword=25, pages=4)
    s.search(["go", "qa"], "Germany", limit=1000)

    assert len(page.urls) == 2          # по одной странице на слово, и всё


def test_a_later_run_starts_from_a_different_query():
    """Бюджет платформы обрывает обход, и без ротации всегда опрашивались бы
    одни и те же первые пары «слово + локация»: остальные роли и страны не
    искались бы никогда, сколько их ни добавь в настройки."""
    def first_keyword(rotate_by):
        page = _FakePage()
        s = _searcher(page, per_keyword=25, rotate_by=rotate_by)
        s.search(["go", "qa", "ai"], "Germany", limit=25)
        return page.urls[0].split("keywords=")[1].split("&")[0]

    assert first_keyword(0) == "go"
    assert first_keyword(1) == "qa"
    assert first_keyword(2) == "ai"
    assert first_keyword(3) == "go"          # по кругу


def test_rotation_still_covers_every_query_in_one_pass():
    page = _FakePage()
    s = _searcher(page, per_keyword=25, rotate_by=2)
    s.search(["go", "qa", "ai"], "Germany", limit=1000)

    asked = {u.split("keywords=")[1].split("&")[0] for u in page.urls}
    assert asked == {"go", "qa", "ai"}


def test_more_than_one_page_is_walked_when_configured():
    page = _FakePage()
    s = _searcher(page, per_keyword=25, pages=3)
    s.search(["go developer"], "Germany", limit=1000)

    assert len(page.urls) == 3
    assert "start=" not in page.urls[0]
    assert "start=25" in page.urls[1]
    assert "start=50" in page.urls[2]


def test_an_empty_page_stops_the_pagination():
    """Дальше пустой страницы вакансий нет — ходить по следующим смысла нет."""
    page = _FakePage()
    s = _searcher(page, cards_per_page=0, per_keyword=25, pages=5)
    s.search(["go developer"], "Germany", limit=1000)

    assert len(page.urls) == 1


# --- сбор карточек с виртуализированного списка ------------------------------
#
# Замер живой страницы 2026-08-03: li[data-occludable-job-id] -> 25, а
# div.job-card-container -> 7. LinkedIn не отрисовывает карточки вне экрана и
# перерабатывает их при скролле (после прокрутки стало 10, а не 25). То есть
# видеть все 25 сразу нельзя в принципе — их надо накапливать по ходу скролла.
# Идентификатор при этом есть у всех сразу, прямо в атрибуте.

def test_all_jobs_are_collected_even_though_only_some_are_rendered():
    from app.infrastructure.search.linkedin_search import merge_harvest
    cards = merge_harvest([
        [{"id": "1", "title": "Go Dev", "company": "Acme", "location": "Berlin"},
         {"id": "2", "title": "", "company": "", "location": ""}],
        [{"id": "2", "title": "QA Engineer", "company": "Beta", "location": "Remote"}],
    ])
    assert [c.get_href() for c in cards] == [
        "https://www.linkedin.com/jobs/view/1/",
        "https://www.linkedin.com/jobs/view/2/",
    ]
    assert cards[1].get_text("title") == "QA Engineer"


def test_a_job_seen_twice_is_not_duplicated():
    from app.infrastructure.search.linkedin_search import merge_harvest
    cards = merge_harvest([
        [{"id": "7", "title": "Go Dev", "company": "Acme", "location": "Berlin"}],
        [{"id": "7", "title": "Go Dev", "company": "Acme", "location": "Berlin"}],
    ])
    assert len(cards) == 1


def test_a_job_that_never_rendered_still_yields_its_link():
    """Заголовок — приятный бонус: описание всё равно читается с самой страницы
    вакансии. А вот потерять ссылку значит потерять вакансию совсем."""
    from app.infrastructure.search.linkedin_search import merge_harvest
    cards = merge_harvest([[{"id": "9", "title": "", "company": "", "location": ""}]])
    assert cards[0].get_href() == "https://www.linkedin.com/jobs/view/9/"
    assert cards[0].get_text("title") == ""


def test_rows_without_an_id_are_dropped():
    from app.infrastructure.search.linkedin_search import merge_harvest
    assert merge_harvest([[{"id": "", "title": "x"}, {"title": "y"}]]) == []


def test_parse_people_cards_maps_profiles():
    cards = [_FakeCard("Jane Recruiter", "Tech Recruiter @ Acme", "",
                       "https://www.linkedin.com/in/jane")]
    out = parse_people_cards(cards, limit=10)
    assert out[0].kind == "profile"
    assert out[0].title == "Jane Recruiter"
    assert out[0].company == "Tech Recruiter @ Acme"
    assert out[0].url == "https://www.linkedin.com/in/jane"
