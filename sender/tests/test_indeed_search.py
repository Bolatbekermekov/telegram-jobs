"""Поиск по Indeed: живой Chrome по отладочному порту, как у Wellfound.

Замер 2026-09-12, реальный Chrome на `indeed.com/jobs?q=ai+engineer&l=Remote`:
32 карточки, ни одного челленджа. Тот же запрос обычным HTTP-клиентом — 403
Cloudflare. Отсюда CDP: своим браузером площадку не открыть.

Вторая половина замера решает, что попадёт в очередь. Из 25 карточек ни одной
с внутренним «Easily apply» — все ведут на сайт компании, и это хорошо. Но
локации сплошь «Remote in Chicago, IL», «Remote in New York, NY», то есть
американская удалёнка, а в тексте таких вакансий стоит «must be currently
authorized to work in the United States». Кандидату из Казахстана они
недоступны, поэтому требование поднимается отдельной строкой в текст для
скорера — иначе он оценивает вакансию по стеку и рекомендует недостижимое.
"""
import pytest

from app.infrastructure.search.indeed_search import (
    IndeedSearcher, build_jobs_url, parse_indeed_cards, work_authorization_note,
)

KEYWORDS = ["ai engineer", "python developer"]


class _FakeCard:
    def __init__(self, title, company, location, href):
        self._d = {"title": title, "company": company, "location": location}
        self._href = href

    def get_text(self, role):
        return (self._d.get(role) or "").strip()

    def get_href(self):
        return self._href


def _card(title="AI Engineer", company="Pulsora", location="Remote in Chicago, IL",
          href="https://www.indeed.com/viewjob?jk=5a8e2f18a0bdf37f"):
    return _FakeCard(title, company, location, href)


# --- разбор карточек ------------------------------------------------------

def test_a_card_becomes_a_candidate():
    [c] = parse_indeed_cards([_card()], limit=10)
    assert c.platform == "indeed"
    assert c.title == "AI Engineer"
    assert c.company == "Pulsora"
    assert c.location == "Remote in Chicago, IL"
    assert c.url == "https://www.indeed.com/viewjob?jk=5a8e2f18a0bdf37f"
    assert c.summary == "", "пересказ пишет скорер, не поиск"


def test_a_card_without_a_job_key_is_dropped():
    """Выдача мешает в список рекламные блоки и ссылки на компании."""
    junk = _card(href="https://www.indeed.com/cmp/Pulsora")
    assert parse_indeed_cards([junk], limit=10) == []


def test_the_same_vacancy_twice_is_returned_once():
    """Одна карточка дублируется в разметке: замер дал 32 узла на 16 вакансий."""
    assert len(parse_indeed_cards([_card(), _card()], limit=10)) == 1


def test_the_limit_is_respected():
    cards = [_card(href=f"https://www.indeed.com/viewjob?jk={i:016x}")
             for i in range(10)]
    assert len(parse_indeed_cards(cards, limit=3)) == 3


# --- адрес выдачи ---------------------------------------------------------

def test_the_query_and_location_reach_the_url():
    url = build_jobs_url("ai engineer", "Remote", page=1)
    assert "q=ai+engineer" in url or "q=ai%20engineer" in url
    assert "l=Remote" in url


def test_pagination_uses_indeeds_step_of_ten():
    """У Indeed смещение в штуках, а не в страницах: start=0, 10, 20."""
    assert "start=0" in build_jobs_url("ai engineer", "Remote", page=1)
    assert "start=10" in build_jobs_url("ai engineer", "Remote", page=2)
    assert "start=30" in build_jobs_url("ai engineer", "Remote", page=4)


# --- право на работу ------------------------------------------------------

def test_a_us_authorization_requirement_is_surfaced():
    """Формулировки сняты с живых вакансий выдачи 2026-09-12."""
    text = ("We are hiring a Senior AI Engineer. Applicants must be currently "
            "authorized to work in the United States on a full-time basis.")
    note = work_authorization_note(text)
    assert note and "United States" in note


def test_a_no_sponsorship_clause_counts_too():
    note = work_authorization_note("We are unable to provide visa sponsorship.")
    assert note


def test_a_vacancy_without_such_a_clause_gets_no_note():
    assert work_authorization_note("Remote, EMEA. We hire across Europe.") == ""


def test_the_note_rides_along_with_the_description():
    """Скорер читает один текст: без склейки требование до него не доедет."""
    page = ("Senior AI Engineer. Build LLM agents. Applicants must be "
            "authorized to work in the United States.")
    s = IndeedSearcher(cdp_url="http://127.0.0.1:9226")
    s._page = _FakeDescribePage(page)
    described = s.describe("https://www.indeed.com/viewjob?jk=1")
    assert "LLM agents" in described
    assert "United States" in described


class _FakeDescribePage:
    def __init__(self, text):
        self._text = text
        self.visited = []

    def goto(self, url, **kw):
        self.visited.append(url)

    def wait_for_selector(self, selector, timeout=None, state=None):
        pass

    def locator(self, selector):
        text = self._text

        class _Loc:
            @property
            def first(self_inner):
                return self_inner

            def inner_text(self_inner, timeout=None):
                return text

        return _Loc()


# --- сам поиск ------------------------------------------------------------

class _FakePage:
    """Отвечает ровно на то, что зовёт searcher: wait_for_selector, evaluate, goto."""

    def __init__(self, rows_by_url=None, rows=None):
        self._rows_by_url = rows_by_url or {}
        self._rows = rows
        self.visited = []
        self.waited = []

    def goto(self, url, **kw):
        self.visited.append(url)

    def wait_for_selector(self, selector, timeout=None, state=None):
        self.waited.append(selector)

    def evaluate(self, script):
        if self._rows is not None:
            return self._rows
        return self._rows_by_url.get(self.visited[-1], [])


def _row(jk="5a8e2f18a0bdf37f", title="AI Engineer"):
    return {"title": title, "company": "Pulsora", "location": "Remote",
            "href": f"https://www.indeed.com/viewjob?jk={jk}"}


def _searcher(page, **kw):
    # Пауза между обращениями подменяется ВСЕГДА: без этого соседние тесты
    # начинают спать по-настоящему по 8-20 секунд на запрос. Тот же капкан уже
    # захлопывался на rate_limit.py, поэтому `sleep` и инъектируется.
    kw.setdefault("sleep", lambda seconds: None)
    s = IndeedSearcher(cdp_url="http://127.0.0.1:9226", **kw)
    s._page = page          # обычно ставит start(); в тесте браузер не нужен
    return s


def test_the_search_walks_pages_outside_and_keywords_inside():
    """Бюджет обрывает перебор; при обратном порядке первое слово съело бы его.

    Выдача здесь непустая намеренно: на пустой оба слова уходят в «больше не
    спрашивать» после первой же страницы, и вторая не открывается вовсе — это
    отдельное правило, проверенное соседним тестом.
    """
    page = _FakePage(rows=[_row()])
    _searcher(page, pages=2).search(KEYWORDS, "Remote", 10)
    starts = [u.split("start=")[1].split("&")[0] for u in page.visited]
    assert starts == ["0", "0", "10", "10"]


def test_a_keyword_that_gave_nothing_is_not_asked_again():
    """Иначе на каждой следующей странице оно стоит ожидания селектора."""
    page = _FakePage(rows=[])
    _searcher(page, pages=3).search(["ai engineer"], "Remote", 10)
    assert len(page.visited) == 1


def test_results_from_different_keywords_are_deduped():
    page = _FakePage(rows=[_row()])
    found = _searcher(page, pages=1).search(KEYWORDS, "Remote", 10)
    assert len(found) == 1


def test_it_declares_that_it_needs_the_users_chrome():
    """`uses_cdp` читает цикл прогона, чтобы предупредить о мёртвом порте."""
    assert IndeedSearcher(cdp_url="http://127.0.0.1:9226").uses_cdp is True


def test_start_and_stop_do_not_close_the_users_browser():
    """Chrome принадлежит человеку: мы только отключаемся."""
    s = IndeedSearcher(cdp_url="http://127.0.0.1:9226")
    s.stop()          # без start() тоже не должно падать


def test_the_dedup_key_is_the_job_id_not_the_normalised_url():
    """`normalize_url` выбрасывает query, а у Indeed вакансия адресуется ей.

    С общим ключом вся выдача схлопывалась бы в один `indeed.com/viewjob`, то
    есть из тридцати вакансий в очередь попадала бы одна.
    """
    cards = [_card(href="https://www.indeed.com/viewjob?jk=aaaaaaaaaaaaaaaa"),
             _card(href="https://www.indeed.com/viewjob?jk=bbbbbbbbbbbbbbbb")]
    assert len(parse_indeed_cards(cards, limit=10)) == 2


def test_the_description_comes_from_the_job_block_not_the_whole_page():
    """Живьём 2026-09-12: `body` отдаёт шапку Indeed («Skip to main content,
    Home, Company reviews, Sign in…»), и у одной из двух вакансий этой шапкой
    текст и исчерпывался — 980 символов, из них описания почти ноль.

    Этот текст идёт в скоринг И в письмо рекрутёру, поэтому берём блок вакансии.
    """
    class _Page:
        def goto(self, url, **kw): pass
        def wait_for_selector(self, selector, timeout=None, state=None): pass

        def locator(self, selector):
            text = ("Build LLM agents with LangGraph."
                    if selector == '[data-testid="viewjob-job-content"]'
                    else "Skip to main content Home Company reviews Sign in Build LLM agents")

            class _Loc:
                @property
                def first(self_inner): return self_inner
                def inner_text(self_inner, timeout=None): return text
            return _Loc()

    s = IndeedSearcher(cdp_url="http://127.0.0.1:9226")
    s._page = _Page()
    got = s.describe("https://www.indeed.com/viewjob?jk=1")
    assert got == "Build LLM agents with LangGraph."
    assert "Company reviews" not in got


def test_without_the_job_block_the_page_body_is_the_fallback():
    """Вёрстка меняется; остаться совсем без текста хуже, чем с шумной шапкой."""
    class _Page:
        def goto(self, url, **kw): pass
        def wait_for_selector(self, selector, timeout=None, state=None): pass

        def locator(self, selector):
            if selector != "body":
                raise RuntimeError("блока с таким селектором нет")

            class _Loc:
                @property
                def first(self_inner): return self_inner
                def inner_text(self_inner, timeout=None): return "Senior AI Engineer, remote EMEA."
            return _Loc()

    s = IndeedSearcher(cdp_url="http://127.0.0.1:9226")
    s._page = _Page()
    assert "EMEA" in s.describe("https://www.indeed.com/viewjob?jk=1")


# --- сбой не должен выглядеть как пустой день -----------------------------

def test_a_challenge_page_is_not_an_empty_day():
    """Живьём 2026-09-12: прогон отдал «пусто» за 4 м 32 с, и это были
    четырнадцать таймаутов ожидания карточек подряд — страница в тот момент не
    отрисовалась. Через двадцать минут тот же запрос дал 10 вакансий за 2 с.

    Пустая выдача и не открывшаяся страница обязаны различаться: первое —
    нормальный рабочий день, второе — повод поднять Chrome и посмотреть.
    """
    from app.infrastructure.search.indeed_search import page_state
    assert page_state("Just a moment...", "Verify you are human", 0) == "challenge"
    assert page_state("Security Check - Indeed.com", "", 0) == "challenge"


def test_a_page_with_cards_is_ready_whatever_the_title_says():
    from app.infrastructure.search.indeed_search import page_state
    assert page_state("Just a moment...", "", 12) == "ready"


def test_a_genuinely_empty_result_stays_empty():
    from app.infrastructure.search.indeed_search import page_state
    assert page_state("golang developer jobs", "no jobs match your search", 0) == "empty"


def test_the_searcher_raises_on_a_challenge_instead_of_reporting_nothing():
    """`run_search` ловит исключение и пишет «ошибка» вместо «пусто»."""
    class _Page:
        url = "https://www.indeed.com/jobs?q=x"
        def goto(self, url, **kw): pass
        def title(self): return "Just a moment..."
        def wait_for_selector(self, selector, timeout=None, state=None):
            raise TimeoutError("no cards")
        def evaluate(self, script): return 0
        def locator(self, selector):
            class _Loc:
                @property
                def first(self_inner): return self_inner
                def inner_text(self_inner, timeout=None): return "Verify you are human"
            return _Loc()

    s = IndeedSearcher(cdp_url="http://127.0.0.1:9226", sleep=lambda x: None)
    s._page = _Page()
    with pytest.raises(RuntimeError, match="login_indeed"):
        s.search(["ai engineer"], "", 5)


# --- своя выборка ключевых слов -------------------------------------------

def test_indeed_searches_its_own_keywords_not_the_global_list():
    """Площадка ищет ТОЛЬКО AI-роли, независимо от общего SEARCH_KEYWORDS.

    Решение владельца 2026-09-12. Причина в устройстве выдачи: Indeed привязан к
    США, и по общим словам («golang developer», «qa engineer») он возвращает
    американскую удалёнку, закрытую для кандидата правом на работу. AI-роли —
    единственная часть выдачи, где хватает международных вакансий, чтобы
    площадка окупала прогон.
    """
    page = _FakePage(rows=[])
    s = _searcher(page, keywords=["ai engineer", "llm engineer"], pages=1)
    s.search(["golang developer", "qa engineer"], "", 10)
    asked = [u.split("q=")[1].split("&")[0] for u in page.visited]
    assert asked == ["ai+engineer", "llm+engineer"]


def test_without_its_own_list_the_global_keywords_are_used():
    """Пустая настройка = прежнее поведение, а не пустой поиск."""
    page = _FakePage(rows=[])
    _searcher(page, keywords=None, pages=1).search(["golang developer"], "", 10)
    assert "q=golang+developer" in page.visited[0]


def test_no_seniority_is_filtered_out():
    """«Любой grade»: уровень не фильтруется ни словом, ни параметром выдачи."""
    url = build_jobs_url("ai engineer", "Remote", page=1)
    for level in ("senior", "junior", "lead", "principal", "explvl"):
        assert level not in url.lower()


def test_cards_are_awaited_as_attached_not_visible():
    """Первая ссылка на вакансию в разметке Indeed НЕвидима.

    Живьём 2026-09-12: `querySelectorAll` находит 35 карточек, а
    `wait_for_selector` по умолчанию ждёт видимости и падает по таймауту — и так
    шесть раз подряд, отчего боевой поиск дважды вернул «пусто» при полной
    странице. Сборщик читает DOM целиком, видимость ему безразлична.
    """
    seen = {}

    class _Page:
        def goto(self, url, **kw): pass
        def wait_for_selector(self, selector, timeout=None, state=None):
            seen["state"] = state
        def evaluate(self, script): return []

    s = IndeedSearcher(cdp_url="http://127.0.0.1:9226")
    s._page = _Page()
    s.job_cards_for_test()
    assert seen["state"] == "attached"


# --- темп запросов --------------------------------------------------------

def test_the_search_pauses_between_pages():
    """Площадка ловит нас по частоте, а не по одному запросу.

    Замер 2026-09-12: одиночные обращения проходят (12 и 35 карточек в разных
    попытках), шесть подряд дают «Security Check - Indeed.com» с Ray ID — в том
    же настоящем Chrome, где ручной просмотр работает. Пауза между страницами
    это единственное, чем мы можем на это повлиять, не обходя саму проверку.
    """
    page = _FakePage(rows=[_row()])
    slept = []
    s = _searcher(page, keywords=["ai engineer", "llm engineer"], pages=1,
                  sleep=slept.append)
    s.search([], "", 10)
    assert len(slept) == 2, "по паузе на каждое обращение"
    assert all(x > 0 for x in slept)


def test_the_pause_is_not_the_same_every_time():
    """Ровный интервал сам по себе выглядит машиной."""
    page = _FakePage(rows=[_row()])
    slept = []
    s = _searcher(page, keywords=["a", "b", "c", "d", "e", "f"], pages=1,
                  sleep=slept.append)
    s.search([], "", 10)
    assert len(set(slept)) > 1, f"паузы одинаковые: {slept}"


def test_without_an_injected_sleep_the_search_still_runs():
    page = _FakePage(rows=[])
    _searcher(page, keywords=["ai engineer"], pages=1, sleep=lambda s: None) \
        .search([], "", 10)
