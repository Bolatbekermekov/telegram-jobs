"""Путь от карточки Indeed до формы работодателя. Чистая логика, без браузера.

Замер живой выдачи 2026-09-12 (реальный Chrome, `indeed.com/jobs?q=ai+engineer`):

* обычный HTTP-клиент получает 403 от Cloudflare, живой Chrome — 200 и
  32 карточки. Отсюда весь транспорт площадки через CDP, как у Wellfound;
* карточка адресуется параметром `jk` (16 hex), а не слагом;
* в выборке из 25 карточек НИ ОДНОЙ с внутренним «Easily apply» — все ведут
  «Apply on company site», то есть редиректом на ATS работодателя. Это и есть
  ценность площадки для нас: формы этих ATS `external_apply` уже заполняет;
* адрес работодателя в разметке страницы НЕ лежит — он раскрывается только
  переходом, поэтому его и приходится проходить браузером.

Две стены самого Indeed, которые надо отличать от нормального ухода на ATS:
`/applystart` — это Indeed Apply, форма живёт на самом Indeed и ATS-хоста за
ней нет; `secure.indeed.com` и `/challenge` — вход и антибот.
"""
from app.domain.indeed_apply import (
    apply_path, job_key, left_indeed, wall_reason,
)

JOB = "https://www.indeed.com/viewjob?jk=591fcde7d2cf0699"


# --- id вакансии ----------------------------------------------------------

def test_the_key_comes_out_of_a_viewjob_link():
    assert job_key(JOB) == "591fcde7d2cf0699"


def test_the_key_survives_extra_query_params():
    """Выдача клеит к ссылке свои метки — они не должны попадать в id."""
    url = JOB + "&from=serp&vjs=3&tk=1abc"
    assert job_key(url) == "591fcde7d2cf0699"


def test_a_redirect_link_carries_the_same_key():
    assert job_key("https://www.indeed.com/rc/clk?jk=591fcde7d2cf0699&fccid=x") \
        == "591fcde7d2cf0699"


def test_something_that_is_not_a_vacancy_has_no_key():
    for url in ("https://www.indeed.com/jobs?q=ai+engineer",
                "https://www.indeed.com/", "", None):
        assert job_key(url) == "", url


def test_the_apply_path_is_relative():
    """Относительная намеренно: переход идёт СО страницы вакансии, и Referer —
    единственное, что отличает нас от прямого захода, который Indeed отбивает."""
    path = apply_path("591fcde7d2cf0699")
    assert path.startswith("/") and "591fcde7d2cf0699" in path


# --- ушли ли мы с площадки ------------------------------------------------

def test_an_employer_ats_means_we_left():
    assert left_indeed("https://boards.greenhouse.io/acme/jobs/123") is True


def test_every_indeed_host_still_counts_as_the_board():
    """У площадки десятки страновых доменов, и все они — всё ещё Indeed."""
    for url in ("https://www.indeed.com/viewjob?jk=1",
                "https://de.indeed.com/jobs?q=ai",
                "https://secure.indeed.com/account/login",
                "https://indeed.com/"):
        assert left_indeed(url) is False, url


def test_a_lookalike_domain_is_not_indeed():
    """`indeed.com.evil.example` не должен сойти за площадку."""
    assert left_indeed("https://indeed.com.evil.example/x") is True


# --- стены самого Indeed --------------------------------------------------

def test_an_open_road_has_no_reason():
    assert wall_reason("https://jobs.lever.co/acme/uuid", JOB) is None


def test_indeed_apply_is_named_as_such():
    """Форма живёт на самом Indeed, ATS за ней нет — заполнять нечего.

    Отдельная формулировка, а не общий отказ: это не поломка, а устройство
    вакансии, и человеку надо понимать, что переоткрывать её бесполезно.
    """
    note = wall_reason("https://www.indeed.com/applystart?jk=591fcde7d2cf0699", JOB)
    assert note is not None and "Indeed Apply" in note


def test_a_login_wall_names_the_fixing_command():
    note = wall_reason("https://secure.indeed.com/account/login?service=my", JOB)
    assert note is not None and "login_indeed" in note


def test_an_antibot_challenge_is_not_confused_with_a_login():
    note = wall_reason("https://www.indeed.com/challenge?tk=abc", JOB)
    assert note is not None and "login_indeed" not in note


def test_staying_on_the_board_without_a_known_reason_still_stops_us():
    """Неизвестная страница Indeed — не повод гадать: лид уходит в руки."""
    assert wall_reason("https://www.indeed.com/career/advice", JOB) is not None
