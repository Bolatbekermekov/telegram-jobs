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
from app.domain.page_gone import (
    GONE_NOTE, html_says_gone, page_lines, redirect_says_gone,
    spa_shell_says_gone,
)
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


# --- смерть, которую видно только по адресу ----------------------------------
#
# Замер 2026-08-27: 215 ссылок отклика, снятых с 222 случайных карточек remocate
# и прочитанных обычным GET. Мёртвых по нынешнему правилу (404/410 плюс текст
# страницы) — 85. Ещё 53 отвечают ЧЕСТНЫМ 200 и ничего про себя не пишут: сайт
# молча уводит на свою страницу-заглушку, и единственный след — адрес, на
# котором мы оказались. Он уже читается (`resp.url`), так что признак не стоит
# ни одного лишнего запроса.
#
# Две формы, обе снятые живьём:
#
#   * адрес УКОРОТИЛИ до его же родителя — вакансии в нём больше нет:
#       fxpro.bamboohr.com/careers/819    -> /careers
#       wargaming.com/en/careers/vacancy_3329214_nicosia/ -> /en/careers/
#       scorewarrior.recruitee.com/o/…    -> recruitee.com/   (корень чужого хоста)
#   * адресу ПРИПИСАЛИ слово «не найдено»:
#       job-boards.greenhouse.io/checkr/jobs/7733714 -> /checkr?error=true
#       apply.workable.com/vivid-money/j/D551B1C739/ -> /vivid-money/?not_found=true
#       ats.rippling.com/chess/jobs/<uuid>          -> /chess/jobs?rr_message=job_not_found
#       aviasales.com/about/vacancies/4249292      -> /4249292/not-found
#
# Проверка на живых: те же 20 вакансий, что стояли в ленте remocate первыми в
# день замера, — ни одна не помечена. Плюс контроль на одном хосте:
# `fxpro.bamboohr.com/careers/809` (живая) редиректа не даёт вовсе, а
# `/careers/819` (снятая) уходит на `/careers`. Списки BambooHR тех же 13
# компаний подтвердили: ни одного помеченного id в живых вакансиях нет.

def test_a_redirect_up_to_the_parent_page_means_the_posting_is_gone():
    asked = "https://fxpro.bamboohr.com/careers/819?source=aWQ9ODQ%3D"
    landed = "https://fxpro.bamboohr.com/careers"
    assert redirect_says_gone(asked, landed) is True


def test_a_redirect_to_a_not_found_marker_means_the_posting_is_gone():
    assert redirect_says_gone(
        "https://job-boards.greenhouse.io/checkr/jobs/7733714",
        "https://job-boards.greenhouse.io/checkr?error=true") is True
    assert redirect_says_gone(
        "https://apply.workable.com/vivid-money/j/D551B1C739/",
        "https://apply.workable.com/vivid-money/?not_found=true") is True
    assert redirect_says_gone(
        "https://recruiting.paylocity.com/recruiting/jobs/Details/2758/acme",
        "https://recruiting.paylocity.com/recruiting/JobNotFound") is True


def test_a_marker_appended_below_the_vacancy_counts_too():
    """Aviasales не укорачивает адрес, а дописывает: `/4249292/not-found`."""
    assert redirect_says_gone(
        "https://www.aviasales.com/about/vacancies/4249292",
        "https://www.aviasales.com/about/vacancies/4249292/not-found") is True


def test_landing_on_the_root_of_somebody_elses_host_is_gone():
    """Recruitee и Personio отправляют снятую вакансию на свою витрину."""
    assert redirect_says_gone(
        "https://scorewarrior.recruitee.com/o/senior-system-engineer-2",
        "https://recruitee.com/") is True
    assert redirect_says_gone(
        "https://smartpricing.jobs.personio.com/job/1682529?display=en",
        "https://www.personio.com/") is True


# --- и ни одного из безобидных ------------------------------------------------
# Похоронить живую вакансию дороже, чем пропустить мёртвую: пропущенная стоит
# одной генерации, похороненная — самой вакансии. Поэтому правило смотрит только
# на ПУТЬ и только на его укорачивание.

def test_www_and_scheme_are_not_a_death():
    assert redirect_says_gone("http://acme.com/jobs/123",
                              "https://www.acme.com/jobs/123") is False
    assert redirect_says_gone("https://www.acme.com/jobs/123",
                              "https://acme.com/jobs/123") is False


def test_a_trailing_slash_is_not_a_death():
    assert redirect_says_gone(
        "https://careers.zeroavia.com/jobs/5ab171/chief-engineer-kemble-united-kingdom",
        "https://careers.zeroavia.com/jobs/5ab171/chief-engineer-kemble-united-kingdom/"
    ) is False


def test_a_locale_swap_is_not_a_death():
    """mediacube.io уводит `/en-AR/` на `/en/`, вакансия та же."""
    assert redirect_says_gone(
        "https://mediacube.io/en-AR/vacancies/business-development-manager-96",
        "https://mediacube.io/en/vacancies/business-development-manager-96") is False


def test_a_new_slug_for_the_same_vacancy_is_not_a_death():
    """Teamtailor дописывает к id название роли, Huntflow переименовал хост."""
    assert redirect_says_gone(
        "https://alberblanc.teamtailor.com/jobs/4894006",
        "https://alberblanc.teamtailor.com/jobs/4894006-quantitative-analyst") is False
    assert redirect_says_gone(
        "https://vertex.huntflow.io/vacancy/senior-devops-engineer-1",
        "https://apicworld.huntflow.io/vacancy/senior-devops-engineer-1") is False
    assert redirect_says_gone(
        "https://www.transparent-hiring.com/jobs/tech-recruiter/",
        "https://www.transparent-hiring.com/jobs/it-recruiter/") is False


def test_a_renamed_section_is_not_a_death():
    """Stripe перевёз `/jobs/search` в `/careers/search`, `gh_jid` на месте."""
    assert redirect_says_gone("https://stripe.com/jobs/search?gh_jid=7923191",
                              "https://stripe.com/careers/search?gh_jid=7923191") is False


def test_dropping_the_apply_step_is_not_a_death():
    """`/jobs/<id>/apply` -> `/jobs/<id>`: сняли ДЕЙСТВИЕ, а не вакансию. Обратный
    ход у Lever ровно такой же и тоже живой: `/<id>/a` -> `/<id>/apply`."""
    assert redirect_says_gone("https://jobs.acme.com/jobs/123/apply",
                              "https://jobs.acme.com/jobs/123") is False
    assert redirect_says_gone(
        "https://jobs.lever.co/easybrain/14c15acb-eaf8-4f3e-aa42-9dcd8ed8eaca/a",
        "https://jobs.lever.co/easybrain/14c15acb-eaf8-4f3e-aa42-9dcd8ed8eaca/apply"
    ) is False


def test_losing_a_tracking_param_is_not_a_death():
    """Путь тот же — вакансия та же, что бы сайт ни сделал с запросом."""
    assert redirect_says_gone("https://acme.com/jobs/123?utm_source=remocate",
                              "https://acme.com/jobs/123") is False


def test_no_redirect_at_all_is_not_a_death():
    assert redirect_says_gone("https://acme.com/jobs/123",
                              "https://acme.com/jobs/123") is False
    assert redirect_says_gone("https://acme.com/jobs/123", "") is False
    assert redirect_says_gone("", "https://acme.com/") is False


# --- и то же самое через саму проверку ---------------------------------------

def test_a_two_hundred_that_redirected_off_the_vacancy_is_a_dead_lead():
    """Ровно тот случай, ради которого признак и вводится: сайт отвечает 200,
    страница-заглушка о себе молчит, а вакансии нет."""
    asked = "https://job-boards.greenhouse.io/checkr/jobs/7733714"
    landed = "https://job-boards.greenhouse.io/checkr?error=true"
    board = ("<html><head><title>Jobs at Checkr</title></head>"
             "<body><h1>Open roles</h1><a href='/checkr/jobs/1'>Backend</a></body></html>")
    reads = _Reads({asked: (200, board, landed)})

    assert vacancy_gone(asked, read=reads) == landed


def test_the_same_board_reached_by_its_own_address_is_left_alone():
    """Без редиректа тот же ответ ничего не доказывает: страница-витрина с
    вакансией внутри — обычное дело (`careers.nebius.com/?gh_jid=…` живая)."""
    url = "https://careers.nebius.com/?gh_jid=4919123101"
    board = ("<html><head><title>Open positions at Nebius</title></head>"
             "<body><h1>Find your role</h1></body></html>")

    assert vacancy_gone(url, read=_Reads({url: (200, board, url)})) == ""


def test_a_live_vacancy_that_merely_got_its_address_tidied_survives():
    asked = "https://careers.zeroavia.com/jobs/5ab171/chief-engineer-kemble"
    landed = asked + "/"
    reads = _Reads({asked: (200, LIVE, landed)})

    assert vacancy_gone(asked, read=reads) == ""


# --- SPA-скорлупа: страница молчит, потому что говорить будет JS --------------
#
# Замер 2026-08-27/28. Ashby и Workday рисуют «Job not found» только после JS, а
# дешёвый GET по определению JS не выполняет. Разметка при этом отвечает честным
# 200, ни редирект, ни текст страницы о смерти не говорят — и лид шёл дальше
# живым: на 300 карточках remocate ссылок на Ashby нашлось 13, из них МЁРТВЫХ 4,
# и все четыре наше правило пропускало.
#
# Признак, который виден БЕЗ JS, нашёлся, и он положительный, а не отрицательный:
# оба вендора вкладывают в `<head>` вакансию как schema.org JobPosting
# (`application/ld+json`). Живая страница его несёт ВСЕГДА, снятая — никогда:
#
#   Ashby    206 живых вакансий из 27 досок  — JobPosting есть у 206
#   Workday  195 живых вакансий из 14 арендаторов — есть у 195
#   мёртвые   4 Ashby + 5 Workday, все девять подтверждены ВИДИМЫМ браузером
#             («Job not found», «The page you are looking for doesn't exist.») —
#             нет ни у одной
#
# Отсутствие признака само по себе смертью не считается, и это главное в правиле.
# Два ограничения куплены ложными срабатываниями, найденными в том же замере:
#
#   1. Адрес обязан называть ОДНУ вакансию. Живая вакансия Workday по адресу
#      `…/job/Data-Engineer_R0240103/apply` отдаёт ту же пустую скорлупу (6449 Б):
#      анкету рисует JS после входа. Так же выглядят корень сайта вакансий
#      (`…/en-US/BAH_Jobs`, 8208 Б) и доска Ashby (`jobs.ashbyhq.com/deel`,
#      10767 Б) — всё это ЖИВЫЕ страницы. Судим только форму «одна вакансия»:
#      у Ashby `/<компания>/<uuid>`, у Workday сегмент `job`/`details` с именем
#      вакансии за ним.
#   2. Разметка обязана быть маленькой. Все девять мёртвых уместились в
#      5904–7319 Б, самая маленькая живая — 12355 Б (Workday) и 19231 Б (Ashby).
#      Порог стоит посередине. Условие независимое: перестань вендор класть
#      ld+json в живую страницу — она всё равно останется большой, потому что в
#      ней лежит описание вакансии, и хоронить её мы не начнём.
#
# Правило намеренно НЕ общее. Живых страниц без ld+json на свете сколько угодно;
# сказать «нет разметки — значит мертва» можно только там, где обратное
# измерено. Список вендоров и есть список измеренного.

ASHBY_JOB = "https://jobs.ashbyhq.com/adjoe/3610b4c7-4c2d-4746-8fa0-bd52272a248d"
WORKDAY_JOB = ("https://bdx.wd1.myworkdayjobs.com/en-US/EXTERNAL_CAREER_SITE_USA"
               "/job/Software-Engineer---Remote_R-517078-1")

# Скорлупа снята дословно по форме с живых страниц: у Ashby это ровно 7270 байт
# при любой компании, у Workday 5904–6706. Ни одного слова о вакансии в ней нет.
SHELL = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>Jobs</title><meta name="title" content="Jobs" />
<link rel="icon" href="https://cdn.ashbyprd.com/cdn_assets/favicon.svg"></head>
<body><noscript>You need to enable JavaScript to run this app.</noscript>
<div id="root"><div class="center fade-in">Loading</div></div>
<script>window.__appData = {};</script></body></html>"""

# Живая: тот же каркас, но с вакансией, объявленной в `<head>`. Описание внутри
# ld+json — то самое, из-за которого живая страница не бывает маленькой; повторов
# столько, чтобы фикстура вышла размером с настоящую (самая маленькая живая
# страница Ashby из замера — 19231 Б).
_DESCRIPTION = ("adjoe builds the technologies behind mobile apps growth and "
                "monetization. ") * 260
LIVE_SHELL = f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<title>Senior MLOps Engineer (f/m/d) @ adjoe</title>
<meta property="og:title" content="Senior MLOps Engineer (f/m/d)" />
<script type="application/ld+json">{{"@context":"https://schema.org/",
"@type":"JobPosting","title":"Senior MLOps Engineer (f/m/d)",
"description":"{_DESCRIPTION}"}}</script></head>
<body><div id="root"></div></body></html>"""


def test_the_four_ashby_shells_are_recognised_without_javascript():
    assert spa_shell_says_gone(ASHBY_JOB, SHELL) is True


def test_a_workday_shell_is_recognised_too():
    assert spa_shell_says_gone(WORKDAY_JOB, SHELL) is True


def test_a_vacancy_that_the_vendor_still_declares_is_alive():
    assert spa_shell_says_gone(ASHBY_JOB, LIVE_SHELL) is False
    assert spa_shell_says_gone(WORKDAY_JOB, LIVE_SHELL) is False


def test_the_apply_step_of_a_live_workday_vacancy_is_not_a_dead_vacancy():
    """Замер: `…/job/Data-Engineer_R0240103/apply` у ЖИВОЙ вакансии — 6449 Б
    пустой скорлупы, анкету рисует JS после входа. Адрес называет действие, а не
    вакансию, поэтому правило о нём молчит."""
    base = "https://bah.wd1.myworkdayjobs.com/en-US/BAH_Jobs/job/Data-Engineer_R0240103"
    assert spa_shell_says_gone(base + "/apply", SHELL) is False
    assert spa_shell_says_gone(base + "/apply/useMyLastApplication", SHELL) is False
    assert spa_shell_says_gone(base + "/apply/applyManually", SHELL) is False


def test_a_careers_site_root_is_not_a_dead_vacancy():
    """Живые страницы, тоже отдающие скорлупу: корень сайта Workday (8208 Б) и
    доска Ashby (10767 Б). Ни та ни другая не называет одну вакансию."""
    assert spa_shell_says_gone(
        "https://bah.wd1.myworkdayjobs.com/en-US/BAH_Jobs", SHELL) is False
    assert spa_shell_says_gone("https://jobs.ashbyhq.com/deel", SHELL) is False
    assert spa_shell_says_gone("https://jobs.ashbyhq.com/", SHELL) is False


def test_a_big_page_without_the_marker_is_left_alone():
    """Второе условие независимо от первого: перестань Ashby класть ld+json —
    страница останется большой, и мы её не похороним."""
    big = LIVE_SHELL.replace("application/ld+json", "application/json")
    assert spa_shell_says_gone(ASHBY_JOB, big) is False


def test_only_the_vendors_we_measured_are_judged_this_way():
    """Живых страниц без ld+json на свете сколько угодно — общим это правило быть
    не может. И граница метки та же, что везде: `ashbyhq.com.evil.tld` — не Ashby."""
    assert spa_shell_says_gone("https://jobs.lever.co/acme/1234", SHELL) is False
    assert spa_shell_says_gone(
        "https://careers.acme.com/jobs/123-backend", SHELL) is False
    assert spa_shell_says_gone(
        "https://jobs.ashbyhq.com.evil.tld/acme/"
        "3610b4c7-4c2d-4746-8fa0-bd52272a248d", SHELL) is False


def test_a_vendor_subdomain_is_still_the_vendor():
    """Workday шардит арендаторов по датацентрам — хостов у него много."""
    for host in ("acme.wd1.myworkdayjobs.com", "acme.wd103.myworkdayjobs.com"):
        url = f"https://{host}/en-US/Careers/job/Remote/Data-Engineer_R1"
        assert spa_shell_says_gone(url, SHELL) is True, host


def test_empty_markup_says_nothing():
    assert spa_shell_says_gone(ASHBY_JOB, "") is False
    assert spa_shell_says_gone(ASHBY_JOB, None) is False
    assert spa_shell_says_gone("", SHELL) is False


def test_the_preflight_check_now_sees_the_ashby_shell():
    """Ради этого всё и делалось: лид на снятую вакансию не должен доходить до
    генерации письма."""
    reads = _Reads({ASHBY_JOB: (200, SHELL, ASHBY_JOB)})
    assert vacancy_gone(ASHBY_JOB, read=reads) == ASHBY_JOB


def test_the_preflight_check_leaves_a_live_ashby_vacancy_alone():
    reads = _Reads({ASHBY_JOB: (200, LIVE_SHELL, ASHBY_JOB)})
    assert vacancy_gone(ASHBY_JOB, read=reads) == ""
