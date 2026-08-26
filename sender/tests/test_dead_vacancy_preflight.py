"""Мёртвая вакансия должна обнаруживаться ДО того, как за письмо заплачено.

Замер прогона 2026-08-26 по площадке `remocate`: из двенадцати лидов ЧЕТЫРЕ вели
на закрытые вакансии, и в логе у каждого сначала шло «Генерирую сообщение...», а
уже потом «страница недоступна / вакансия неактуальна». То есть треть лидов
площадки сжигала три вызова модели (классификация роли, письмо, тема) и подъём
браузера на объявление, которого больше нет:

    #414 toughbyte.com/positions/…/full-stack-javascript-developer-3037
    #416 joom-group.breezy.hr/p/df9b90d18230-lead-backend-developer-go-at-joompro
    #420 youhodler.com/careers/engineer-frontend
    #425 joom.potok.io/open/jobs/7413/closed

Разметка в фикстурах ниже снята с этих самых страниц 2026-08-26 обычным GET —
браузер для этого не нужен, и в этом весь смысл: проверка стоит в цикле
отправки, до генерации, и стоит два дешёвых запроса вместо трёх платных.
"""
from app.application.send_plan import dead_vacancy_reason
from app.domain.lead import STATUS_MANUAL
from app.domain.page_gone import GONE_NOTE, html_says_gone, page_lines
from app.infrastructure.vacancy_alive import vacancy_gone

# --- разметка снятых вакансий, дословно по форме с живых страниц -------------

# HTTP 200, заголовок обычный: состояние написано ОДНОЙ отключённой кнопкой.
TOUGHBYTE = """<html><head><title>Full-Stack JavaScript Developer - Toughbyte | Toughbyte</title></head>
<body><div class="flex-column"><h1 class="font-account-header">Full-Stack JavaScript Developer</h1>
<div class="mb-1"><a href="/companies/toughbyte-1">Toughbyte</a></div><div>Remote</div></div>
<div class="hstack gap-2"><button class="btn btn-lg" disabled="disabled">Closed</button>
<div class="d-block"><a href="/positions">view all positions</a></div></div>
<div><b>Roles:</b> <div>Frontend</div><div>Backend</div></div></body></html>"""

# HTTP 200: ATS рисует на месте формы отдельную страницу-заглушку.
BREEZY = """<html><head><title>Lead Backend Developer (Go) at JoomPro at Joom</title></head>
<body><h2 class="company-name"><a href="/" class="back"><span> Joom</span></a></h2>
<div class="confirmation-container"><div class="application-confirmed"><i class="fa fa-frown-o"></i>
<h1>Position Closed</h1><p>Sorry, this position is no longer accepting candidates.</p>
</div></div></body></html>"""

# HTTP 404: и заголовок, и первая строка говорят прямо.
YOUHODLER = """<html><head><title>Not Found</title></head><body><main>
<section class="section-404"><div class="heading-label _404"><h1 class="heading-label_text">404</h1></div>
<div class="heading-style-h1">Looks like we lost<br/>that page...</div>
<a href="/?r=0" class="button">Go Back Home</a></section></main></body></html>"""

# HTTP 404, но заголовок — название вакансии: сайт отдаёт полную страницу компании.
POTOK = """<html><head><title>Lead Backend Developer (Go)</title></head><body>
<div><p>Джум — международная группа компаний в сфере e-commerce.</p></div>
<div class="postings-wrapper"><div class="sort-links">
Эта вакансия закрыта. Попробуйте посмотреть другие вакансии в компании.
</div></div></body></html>"""

# Живая вакансия, нарочно с обеими ловушками: «closed» в описании и «404» в
# требованиях. Ради этого правило «состояние — это ЦЕЛАЯ строка» и держится.
LIVE = """<html><head><title>Senior Backend Engineer — Acme</title></head><body>
<h1>Senior Backend Engineer</h1><div>Remote</div>
<button class="btn">Apply now</button>
<p>We work with <span>closed</span>-source SDKs and a closed beta programme.</p>
<p>You will handle 404 and 500 responses in our API gateway.</p>
<p>Applications are not closed to juniors.</p></body></html>"""


def test_all_four_dead_pages_are_recognised_from_plain_markup():
    """Тот же вердикт, что вынес браузер в прогоне, — но без браузера."""
    assert html_says_gone(TOUGHBYTE) is True
    assert html_says_gone(BREEZY) is True
    assert html_says_gone(YOUHODLER) is True
    assert html_says_gone(POTOK) is True


def test_a_live_vacancy_survives_both_traps():
    assert html_says_gone(LIVE) is False


def test_a_disabled_button_counts_as_its_own_line():
    """Toughbyte пишет состояние как `<button disabled>Closed</button>`, а рядом
    в той же обёртке лежит ссылка «view all positions». Склей их в одну строку —
    и правило «состояние стоит отдельной строкой» промахнётся."""
    assert "Closed" in page_lines(TOUGHBYTE).splitlines()


def test_an_inline_word_does_not_become_a_line_of_its_own():
    """`<span>closed</span>` внутри «closed-source» — не состояние страницы."""
    assert html_says_gone(
        "<html><body><p>We ship <span>closed</span>-source SDKs.</p></body></html>"
    ) is False


def test_empty_markup_says_nothing():
    assert html_says_gone("") is False
    assert html_says_gone(None) is False


# --- один дешёвый запрос вместо трёх платных --------------------------------

class _Reads:
    """Подставной читатель страниц: (код, разметка, конечный адрес)."""

    def __init__(self, answers):
        self._answers = answers
        self.asked = []

    def __call__(self, url, timeout):
        self.asked.append(url)
        return self._answers.get(url, (-1, "", ""))


JOB = "https://www.remocate.app/jobs/lead-backend-developer-go-joompro"
EMPLOYER = "https://joom-group.breezy.hr/p/df9b90d18230-lead-backend-developer-go-at-joompro"
AGGREGATOR_PAGE = f"""<html><head><title>Lead Backend Developer (Go) at Joom</title></head>
<body><a href="https://cdn.prod.website-files.com/x.svg">logo</a>
<a href="https://twitter.com/remocate">tw</a>
<h1>Lead Backend Developer (Go)</h1><p>Build the marketplace backend.</p>
<a href="{EMPLOYER}">Apply for this job</a></body></html>"""


def test_a_404_is_the_site_saying_the_posting_is_gone():
    reads = _Reads({"https://www.youhodler.com/careers/engineer-frontend":
                    (404, YOUHODLER, "https://www.youhodler.com/careers/engineer-frontend")})
    assert vacancy_gone("https://www.youhodler.com/careers/engineer-frontend",
                        read=reads) == "https://www.youhodler.com/careers/engineer-frontend"


def test_a_410_is_gone_too():
    """Замер 2026-08-26: из четырнадцати случайных объявлений remocate восемь
    вели на 404/410 у работодателя — площадка держит устаревшие карточки."""
    url = "https://careers.sumsub.com/jobs/5316456-content-production-lead"
    reads = _Reads({url: (410, "", url)})
    assert vacancy_gone(url, read=reads) == url


def test_a_two_hundred_page_that_says_closed_is_gone():
    url = "https://www.toughbyte.com/positions/remote/toughbyte-1/x-3037"
    reads = _Reads({url: (200, TOUGHBYTE, url)})
    assert vacancy_gone(url, read=reads) == url


def test_a_live_page_is_left_alone():
    url = "https://jobs.lever.co/acme/1"
    reads = _Reads({url: (200, LIVE, url)})
    assert vacancy_gone(url, read=reads) == ""


def test_a_timeout_is_not_a_dead_vacancy():
    """Недоступный на секунду сайт — не повод хоронить лид. Это дороже скорости:
    пропущенная мёртвая вакансия стоит одной генерации, похороненная живая —
    самой вакансии."""
    url = "https://jobs.lever.co/acme/1"
    assert vacancy_gone(url, read=_Reads({})) == ""          # -1: читатель не смог


def test_a_403_is_not_a_dead_vacancy():
    """403 — «нас не пустили», а не «вакансии нет». Cloudflare отвечает так же."""
    url = "https://jobs.lever.co/acme/1"
    assert vacancy_gone(url, read=_Reads({url: (403, "", url)})) == ""


def test_a_server_error_is_not_a_dead_vacancy():
    url = "https://jobs.lever.co/acme/1"
    assert vacancy_gone(url, read=_Reads({url: (503, "", url)})) == ""


def test_the_note_names_the_address_that_actually_answered():
    """Сайт увёл на свою страницу «вакансия закрыта» — в заметке должен стоять
    тот адрес, который человек откроет и увидит то же самое. Так же поступает и
    канал: он пишет `obs.url`, то есть где браузер в итоге оказался."""
    asked = "https://joom.potok.io/open/jobs/7413"
    landed = "https://joom.potok.io/open/jobs/7413/closed"
    reads = _Reads({asked: (404, POTOK, landed)})

    assert vacancy_gone(asked, read=reads) == landed


def test_a_reader_that_blows_up_costs_the_check_not_the_run():
    def _boom(url, timeout):
        raise RuntimeError("сеть отвалилась")

    assert vacancy_gone("https://jobs.lever.co/acme/1", read=_boom) == ""


def test_the_aggregator_hop_finds_the_employer_page_that_died():
    """Карточка на remocate живёт своей жизнью — умирает страница работодателя.
    Все четыре мёртвых лида прогона были именно такими."""
    reads = _Reads({JOB: (200, AGGREGATOR_PAGE, JOB), EMPLOYER: (200, BREEZY, EMPLOYER)})

    assert vacancy_gone(JOB, read=reads) == EMPLOYER
    assert reads.asked == [JOB, EMPLOYER]


def test_a_live_aggregator_lead_costs_exactly_two_reads():
    reads = _Reads({JOB: (200, AGGREGATOR_PAGE, JOB), EMPLOYER: (200, LIVE, EMPLOYER)})

    assert vacancy_gone(JOB, read=reads) == ""
    assert reads.asked == [JOB, EMPLOYER]


def test_a_delisted_aggregator_card_needs_no_second_hop():
    reads = _Reads({JOB: (404, "", JOB)})

    assert vacancy_gone(JOB, read=reads) == JOB
    assert reads.asked == [JOB]


def test_an_ambiguous_aggregator_page_is_not_a_verdict():
    """Двух работодателей на странице канал уже отдаёт человеку — угадывать
    нельзя и здесь, поэтому второго запроса просто нет."""
    ambiguous = AGGREGATOR_PAGE.replace(
        "<h1>", '<a href="https://jobs.lever.co/other/1">x</a><h1>')
    reads = _Reads({JOB: (200, ambiguous, JOB)})

    assert vacancy_gone(JOB, read=reads) == ""
    assert reads.asked == [JOB]


def test_a_plain_employer_page_is_never_hopped_from():
    """Прыжок за ссылкой отклика осмыслен только на агрегаторе. У обычной
    страницы вакансии внешних ссылок сколько угодно, и любая из них — не она."""
    url = "https://jobs.lever.co/acme/1"
    page = '<html><body><a href="https://acme.com/about">About</a>жив</body></html>'
    reads = _Reads({url: (200, page, url)})

    assert vacancy_gone(url, read=reads) == ""
    assert reads.asked == [url]


# --- кому эта проверка вообще адресована ------------------------------------

def _never(url, timeout=None):
    raise AssertionError(f"страницу читать было не нужно: {url}")


def test_a_telegram_handle_is_not_a_page_to_read():
    assert dead_vacancy_reason("@hr_acme", _never) is None


def test_an_email_address_is_not_a_page_to_read():
    assert dead_vacancy_reason("jobs@acme.com", _never) is None


def test_a_linkedin_profile_is_a_person_not_a_posting():
    """У профиля цель — человек: пост удалили, а написать ему всё ещё можно."""
    assert dead_vacancy_reason("https://www.linkedin.com/in/someone/", _never) is None
    assert dead_vacancy_reason(
        "https://www.linkedin.com/posts/acme_hiring-activity-7229", _never) is None


def test_a_blank_target_is_somebody_elses_problem():
    assert dead_vacancy_reason("", _never) is None
    assert dead_vacancy_reason(None, _never) is None


def test_every_shape_of_vacancy_page_is_checked():
    seen = []

    def _gone(url):
        seen.append(url)
        return ""

    targets = [
        "https://www.remocate.app/jobs/lead-backend-developer-go-joompro",
        "https://remoteok.com/remote-jobs/1234-backend-acme",
        "https://hh.ru/vacancy/123456",
        "https://www.linkedin.com/jobs/view/4455783459",
    ]
    for t in targets:
        assert dead_vacancy_reason(t, _gone) is None
    assert seen == targets


def test_a_dead_vacancy_parks_the_lead_for_a_human_not_for_the_bin():
    """Жёсткое правило владельца: `skipped` автоматом не проставляется никогда —
    закрытый автоматом лид человек больше не увидит. `manual` — тот же статус,
    которым канал уже отвечает на эту же находку, и та же заметка."""
    status, note = dead_vacancy_reason(
        "https://www.remocate.app/jobs/x", lambda url: EMPLOYER)

    assert status == STATUS_MANUAL
    assert note == f"{GONE_NOTE}: {EMPLOYER}"


def test_the_note_is_worded_exactly_as_the_channel_words_it():
    """Одна находка — одна формулировка в таблице, кто бы её ни сделал: канал,
    открывший страницу браузером, или проверка до генерации. Разойдись они — и в
    листе появятся две разные заметки про одно и то же."""
    from app.infrastructure.channels.external_apply import GONE_NOTE as channel_note

    assert GONE_NOTE == "страница недоступна / вакансия неактуальна"
    assert channel_note is GONE_NOTE
