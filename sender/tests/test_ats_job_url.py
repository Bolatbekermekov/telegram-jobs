"""Ссылка прямо в ATS работодателя (Greenhouse, Lever и прочие) — это вакансия.

До сих пор такая ссылка терялась целиком: ни одно правило `detect_contact` её не
знало, функция отвечала None, и интейк отвечал «⚠️ Не нашёл контакт», не сохраняя
ничего. Контакта у страницы Greenhouse и не может быть — отклик там идёт формой, а
форму заполнять умеет `external_apply` в отправителе.

Формы адресов сняты с живых вакансий 2026-09-11 (замер: статус, время ответа,
наличие текста в сыром HTML):

* Greenhouse держит ДВА хоста разом — старый `boards.greenhouse.io` (редиректит
  на карьерный сайт компании) и новый `job-boards.greenhouse.io`;
* Lever и Ashby адресуют вакансию uuid-ом, SmartRecruiters — числом с текстовым
  хвостом, Workable — коротким кодом после `/j/`;
* корень доски (`/<компания>` без вакансии) вакансией НЕ является: правило
  требует путь, ровно как у агрегаторов, иначе ссылка «мы нанимаем, вот наша
  доска» уедет откликом в никуда.
"""
from app.domain.vacancy_text import (
    is_ats_job_url, is_fetchable_vacancy_url, iter_urls, pick_vacancy_url,
)

GREENHOUSE_OLD = "https://boards.greenhouse.io/block/jobs/5406229008"
GREENHOUSE_NEW = "https://job-boards.greenhouse.io/axios/jobs/7954574"


def test_greenhouse_job_link_is_a_vacancy():
    assert is_ats_job_url(GREENHOUSE_OLD) is True


def test_greenhouse_serves_two_hosts_and_both_count():
    """Компании переезжают со старого хоста на новый, ссылки ходят обе."""
    assert is_ats_job_url(GREENHOUSE_NEW) is True


def test_the_board_itself_is_not_a_vacancy():
    """«Вот наша доска вакансий» — не вакансия: откликаться не на что."""
    assert is_ats_job_url("https://boards.greenhouse.io/block") is False


# Остальные вендоры. Каждый адрес — форма, снятая с живой вакансии: Lever и Ashby
# адресуют uuid-ом, SmartRecruiters числом с текстовым хвостом, Workable коротким
# кодом, Workday прячет вакансию за `/job/`, а Teamtailor, Recruitee и Personio
# живут на поддомене компании.
VENDORS = [
    "https://jobs.lever.co/theathletic/653f1e14-62c1-4439-a504-e436f1cc6d53",
    "https://jobs.ashbyhq.com/ramp/72a7e865-0787-44a6-85e8-d6d4d5a62765",
    "https://apply.workable.com/hospitable/j/A0F082F91A",
    "https://jobs.smartrecruiters.com/WynnResorts/744000146787079-concierge",
    "https://intel.wd1.myworkdayjobs.com/en-US/External/job/Manager_JR0284685",
    "https://everymatrix.teamtailor.com/jobs/8360735-product-owner",
    "https://dnata.recruitee.com/o/manager-facilities-procurement",
    "https://govradar.jobs.personio.com/job/2762043",
]


def test_every_supported_vendor_is_recognised():
    assert [u for u in VENDORS if not is_ats_job_url(u)] == []


# Корень компании у каждого вендора — такой же «не вакансия», как доска
# Greenhouse. Проверяется отдельно от Greenhouse, потому что путь у всех свой и
# ошибиться можно в каждом.
ROOTS = [
    "https://jobs.lever.co/theathletic",
    "https://jobs.ashbyhq.com/ramp",
    "https://apply.workable.com/hospitable",
    "https://everymatrix.teamtailor.com/jobs",
    "https://dnata.recruitee.com",
]


def test_a_company_landing_page_is_not_a_vacancy():
    assert [u for u in ROOTS if is_ats_job_url(u)] == []


def test_platforms_that_already_have_their_own_channel_stay_theirs():
    """hh, LinkedIn и Wellfound откликаются своим кодом, а не чужой формой.

    Они перечислены в `apply_guard.ALLOWED_APPLY_HOSTS` наравне с настоящими
    ATS, и соблазн взять тот список целиком именно здесь и ломается: площадка с
    собственным каналом не должна становиться `ats`.
    """
    theirs = ["https://hh.ru/vacancy/123456789",
              "https://www.linkedin.com/jobs/view/4212345678/",
              "https://wellfound.com/jobs/1234567-backend-engineer"]
    assert [u for u in theirs if is_ats_job_url(u)] == []


# --- ссылку надо сперва НАЙТИ в тексте -----------------------------------

def test_a_bare_ats_link_without_the_scheme_is_still_found():
    """Телефонная вставка и подпись канала роняют `https://`.

    `_URL_RE` ловит бессхемные адреса только по белому списку хостов, и пока ATS
    в него не входят, такая ссылка для интейка просто слова.
    """
    text = "Вакансия тут: boards.greenhouse.io/block/jobs/5406229008"
    assert list(iter_urls(text)) == [GREENHOUSE_OLD]


def test_an_ats_page_is_worth_fetching():
    """Замер 2026-09-11: Greenhouse отдаёт полный текст вакансии за 0.4-3 с."""
    assert is_fetchable_vacancy_url(GREENHOUSE_OLD) is True


def test_the_ats_link_wins_over_prose_around_it():
    text = ("Привет! Смотри какая вакансия, они пишут на Go и Python.\n"
            f"{GREENHOUSE_NEW}\nОткликайся, если интересно.")
    assert pick_vacancy_url(text) == GREENHOUSE_NEW


# --- чтение страницы ------------------------------------------------------
#
# Замер 2026-09-11 по живым вакансиям показал ровно три расклада, и извлечение
# обязано покрывать все три:
#
#   * Greenhouse, Lever, SmartRecruiters, Personio — текст лежит в сыром HTML;
#   * Workday, Teamtailor, Recruitee — видимого текста нет, но есть серверный
#     блок `application/ld+json` с полным описанием;
#   * Ashby и Workable — пустой React-шелл, текста нет нигде.

from app.domain.vacancy_text import extract_ats_vacancy

LD_JSON_PAGE = """<!doctype html><html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"JobPosting",
 "title":"Senior Go Engineer",
 "description":"<p>You will build <b>gateways</b>.</p><p>5+ years of Go.</p>"}
</script></head><body><div id="root"></div></body></html>"""

PLAIN_PAGE = """<!doctype html><html><head><title>Senior Python Engineer</title>
<style>.x{color:red}</style></head><body>
<h1>Senior Python Engineer</h1>
<p>Responsibilities: design and ship FastAPI services.</p>
<script>window.__DATA__ = 1;</script>
</body></html>"""

EMPTY_SHELL = ('<!doctype html><html><body><div id="root"></div>'
               '<noscript>You need to enable JavaScript to run this app.</noscript>'
               '</body></html>')


def test_structured_description_is_preferred_when_the_page_has_one():
    """Workday и Teamtailor выглядят пустыми, но кладут описание в JSON-LD."""
    text = extract_ats_vacancy(LD_JSON_PAGE)
    assert "You will build gateways." in text
    assert "5+ years of Go." in text


def test_a_server_rendered_page_is_read_straight_from_the_html():
    text = extract_ats_vacancy(PLAIN_PAGE)
    assert "design and ship FastAPI services" in text


def test_scripts_and_styles_never_leak_into_the_brief():
    text = extract_ats_vacancy(PLAIN_PAGE)
    assert "window.__DATA__" not in text and "color:red" not in text


def test_an_empty_react_shell_reads_as_nothing():
    """Ashby и Workable: честный «» лучше, чем «enable JavaScript» в брифе."""
    assert extract_ats_vacancy(EMPTY_SHELL) == ""
