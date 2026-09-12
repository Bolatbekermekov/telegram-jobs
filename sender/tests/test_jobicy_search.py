"""Поиск по Jobicy: открытый JSON API, без браузера и без логина.

Замеры живьём 2026-09-11, всё через `jobicy.com/api/v2/remote-jobs`:

* параметр `tag` РАБОТАЕТ, в отличие от игнорируемых параметров Remotive:
  `tag=golang` отдаёт 59, `tag=node.js` — 69, а пересечение выдач `python` и
  `ai engineer` всего 27 из 100, то есть это разные наборы, а не одна лента;
* фраза тоже работает: `tag=ai engineer` возвращает настоящие «AI Engineer …»
  первыми строками;
* фильтр полнотекстовый, по описанию тоже: в выдаче `tag=python` слово Python
  стоит в заголовке лишь у 10 из 100. Поэтому заголовок всё равно проверяется
  своим `title_matches` — иначе в очередь поедут продакты, упомянувшие Python
  в требованиях к команде;
* потолок ответа — 100 вакансий на запрос (`count`).

Отклик тут отдельная история: кнопка «Apply Now» на странице вакансии не
ссылка, а кнопка с событием `RegistrationGateOpened`, и адреса работодателя нет
ни в разметке страницы, ни в попапе, ни в `jobDescription` (проверено на 50
вакансиях: ноль ATS-ссылок). То есть поиск свободен, а отклик требует аккаунта.
"""
import httpx
import pytest

from app.infrastructure.search.jobicy_search import (
    JobicySearcher, parse_jobicy_jobs, strip_html, to_candidate,
)

KEYWORDS = ["python developer", "ai engineer", "golang developer"]


def _job(title="Senior Python Developer", url="https://jobicy.com/jobs/1-senior-python",
         company="Canonical", desc="<p>Build <b>FastAPI</b> services.</p>",
         geo="APAC, EMEA", level="Any", salary=""):
    return {"id": 1, "url": url, "jobTitle": title, "companyName": company,
            "jobDescription": desc, "jobGeo": geo, "jobLevel": level,
            "annualSalaryMin": salary, "jobIndustry": ["Software Engineering"]}


class _Api:
    """Фейк ленты: помнит, каким `tag` её спрашивали."""

    def __init__(self, by_tag=None, jobs=None, boom=None):
        self.by_tag = by_tag or {}
        self.jobs = jobs
        self.boom = boom
        self.asked = []

    def __call__(self, tag, count):
        self.asked.append(tag)
        if self.boom:
            raise self.boom
        if self.jobs is not None:
            return {"jobs": self.jobs}
        return {"jobs": self.by_tag.get(tag, [])}


def _searcher(api):
    return JobicySearcher(fetch=api)


# --- разбор ленты ---------------------------------------------------------

def test_the_jobs_array_is_pulled_out():
    assert parse_jobicy_jobs({"jobs": [_job()]}) == [_job()]


def test_a_malformed_payload_is_not_a_crash():
    assert parse_jobicy_jobs("не словарь") == []
    assert parse_jobicy_jobs({"jobs": ["строка вместо объекта"]}) == []


def test_html_is_stripped_from_the_description():
    assert strip_html("<p>Build <b>FastAPI</b> services.</p>") == "Build FastAPI services."


def test_a_candidate_carries_what_the_sheet_shows():
    c = to_candidate(_job())
    assert c.platform == "jobicy"
    assert c.title == "Senior Python Developer"
    assert c.company == "Canonical"
    assert c.url == "https://jobicy.com/jobs/1-senior-python"
    assert c.summary == "", "пересказ пишет скорер, не поиск"


# --- сам поиск ------------------------------------------------------------

def test_every_keyword_is_asked_for_separately():
    """`tag` реально фильтрует, поэтому спрашиваем по слову, а не режем одну ленту."""
    api = _Api(jobs=[])
    _searcher(api).search(KEYWORDS, "Worldwide", 10)
    assert api.asked == KEYWORDS


def test_a_title_that_does_not_match_the_role_is_dropped():
    """Фильтр площадки полнотекстовый: «VP of Sales» попадает в выдачу
    `tag=python`, потому что Python назван в требованиях к команде."""
    api = _Api(jobs=[_job(title="VP of Sales", desc="<p>Our team writes Python.</p>")])
    assert _searcher(api).search(KEYWORDS, "Worldwide", 10) == []


def test_the_same_vacancy_found_by_two_keywords_is_returned_once():
    """Пересечение выдач измерено: 27 из 100 между `python` и `ai engineer`."""
    api = _Api(jobs=[_job()])
    found = _searcher(api).search(KEYWORDS, "Worldwide", 10)
    assert len(found) == 1


def test_the_limit_stops_the_search_early():
    jobs = [_job(title=f"Senior Python Developer {i}",
                 url=f"https://jobicy.com/jobs/{i}-python") for i in range(10)]
    api = _Api(jobs=jobs)
    assert len(_searcher(api).search(KEYWORDS, "Worldwide", 4)) == 4


def test_the_description_comes_from_the_search_without_a_second_request():
    """Каждая вакансия несёт своё описание — повторный запрос был бы платой ни за что."""
    api = _Api(jobs=[_job()])
    s = _searcher(api)
    s.search(KEYWORDS, "Worldwide", 10)
    before = len(api.asked)
    assert "FastAPI" in s.describe("https://jobicy.com/jobs/1-senior-python")
    assert len(api.asked) == before, "describe() не ходит в сеть"


def test_a_network_failure_is_not_silently_an_empty_day():
    """Пустая выдача — обычный рабочий день площадки, сбой обязан выглядеть иначе.

    Урок RemoteOK: `except Exception: return []` делал 429 неотличимым от
    «сегодня ничего не подошло», и это было нечем поймать.
    """
    api = _Api(boom=httpx.HTTPError("429 Too Many Requests"))
    with pytest.raises(httpx.HTTPError):
        _searcher(api).search(KEYWORDS, "Worldwide", 10)


def test_results_do_not_leak_between_runs():
    api = _Api(jobs=[_job()])
    s = _searcher(api)
    s.search(KEYWORDS, "Worldwide", 10)
    s._fetch = _Api(jobs=[])
    s.search(KEYWORDS, "Worldwide", 10)
    assert s.describe("https://jobicy.com/jobs/1-senior-python") == ""


def test_start_and_stop_are_noops():
    """Ни браузера, ни сессии: площадка отдаёт ленту анонимно."""
    s = _searcher(_Api(jobs=[]))
    s.start()
    s.stop()


# --- регистрация площадки -------------------------------------------------

def test_the_platform_is_in_the_search_order():
    from app.domain.search_request import SEARCH_PLATFORMS
    assert "jobicy" in SEARCH_PLATFORMS


def test_the_registry_builds_it():
    """Площадки нет в реестре — и воркер ловит KeyError на каждом обходе."""
    from app.infrastructure.search.registry import build_searcher
    assert isinstance(build_searcher("jobicy"), JobicySearcher)


def test_it_has_its_own_cli_token():
    from app.application.search_commands import platforms_arg
    assert platforms_arg("search_jobicy") == ["jobicy"]


def test_the_bot_menu_offers_it():
    from register_bot_menu import bot_commands_payload
    assert any(c["command"] == "search_jobicy" for c in bot_commands_payload())
