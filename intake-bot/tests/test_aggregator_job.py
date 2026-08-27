"""Ссылка на агрегатор вакансий, присланная боту, становится лидом.

До 2026-08-22 такой пост терялся целиком: `detect_contact` не знал ни одного
агрегатора, отвечал None, и бот говорил «⚠️ Не нашёл контакт», ничего не сохраняя.
Проверено живьём на трёх формах сообщения — голая ссылка, пост с описанием без
контакта, пост с @ником: в первых двух лид не создавался вовсе, в третьем
создавался как telegram, а ссылка оставалась просто текстом и страница не
читалась.

Разметка агрегатора измерена живьём 2026-08-22 на
`remocate.app/jobs/software-engineering-intern-winter-datadog`:

* JSON-LD нет, og-тегов нет, meta description нет — только `<title>` вида
  «Software Engineering Intern (Winter) at Datadog»;
* текст после снятия тегов начинается прямо с заголовка и содержит компанию,
  тип занятости, уровень, страну и «Job description …»;
* описание кончается на «Apply for this job» (позиция 3894 из 298607), дальше
  идут карточки ЧУЖИХ вакансий — Monetha и прочие, и в бриф им нельзя;
* внешних хостов на странице восемь, и семь из них шум: CDN Webflow, шрифты
  Google, соцсети и поддомены самого агрегатора (lemonsqueezy, betteruptime).
  Осмысленный ровно один — `careers.datadoghq.com`, настоящий адрес отклика.
"""
from app.domain.contact import Contact, detect_contact
from app.domain.vacancy_text import (
    aggregator_apply_url, extract_aggregator_vacancy, is_aggregator_job_url,
    is_fetchable_vacancy_url, is_remoteok_job_url, iter_urls, pick_vacancy_url,
)

JOB = "https://www.remocate.app/jobs/software-engineering-intern-winter-datadog"
APPLY = "https://careers.datadoghq.com/detail/8052095/?gh_jid=8052095"

# Форма страницы воспроизводит замер: те же хосты-шумы, ровно одна осмысленная
# внешняя ссылка, маркер конца описания.
PAGE = f"""<!doctype html><html><head>
<title>Software Engineering Intern (Winter) at Datadog</title>
<link href="https://fonts.googleapis.com/css?family=X" rel="stylesheet">
<link href="https://fonts.gstatic.com/s/x.woff2" rel="preload">
</head><body>
<a href="https://cdn.prod.website-files.com/logo.svg">logo</a>
<a href="https://remocate.lemonsqueezy.com/checkout">Post a job</a>
<a href="https://remocate.betteruptime.com/">status</a>
<a href="https://www.linkedin.com/company/remocate">LinkedIn</a>
<a href="https://twitter.com/remocate">Twitter</a>
<h1>Software Engineering Intern (Winter)</h1>
<div>Datadog</div><div>Full-time</div><div>Junior</div><div>USA</div>
<div>Remote</div><div>Relocation</div>
<h2>Job description</h2>
<p>We are looking for Software Engineering Interns to help build and scale
the systems that power Datadog observability.</p>
<a href="{APPLY}">Apply for this job</a>
<script>var noise = "ignore me";</script>
<h3>Senior Front-end Engineer at Monetha</h3>
<p>Мы ищем фронтендера, и это ЧУЖАЯ вакансия — в бриф ей нельзя.</p>
</body></html>"""


# --- узнаём ссылку -----------------------------------------------------------

def test_an_aggregator_job_link_is_recognised():
    assert is_aggregator_job_url(JOB)
    assert is_aggregator_job_url("remocate.app/jobs/x")      # и без схемы


def test_the_aggregators_other_pages_are_not_vacancies():
    """Правило узкое: сама вакансия, а не блог и не главная."""
    assert not is_aggregator_job_url("https://www.remocate.app/")
    assert not is_aggregator_job_url("https://www.remocate.app/blog/how-to-relocate")


def test_a_look_alike_host_is_not_matched():
    assert not is_aggregator_job_url("https://notremocate.app/jobs/x")


def test_a_remoteok_job_link_is_recognised():
    assert is_remoteok_job_url("https://remoteok.com/remote-jobs/1091234-backend-acme")
    assert not is_remoteok_job_url("https://remoteok.com/")


# --- контакт и маршрут -------------------------------------------------------
# Площадка называется по агрегатору, а не «external»: имя видно в таблице, и
# «external» там не сообщало ни откуда вакансия, ни есть ли под неё
# автоматизация. Драйвер в отправителе при этом общий на все агрегаторы.

def test_a_bare_link_now_becomes_a_lead():
    """Именно то, что раньше отвечало «Не нашёл контакт»."""
    assert detect_contact(JOB) == Contact("remocate", JOB)


def test_the_post_around_the_link_does_not_break_detection():
    text = ("Software Engineering Intern (Winter) в Datadog: " + JOB +
            "\n\nПомогают с релокацией (США). Зарплата в валюте.\n"
            "При отклике укажите, что нашли вакансию на Remocate.")
    assert detect_contact(text) == Contact("remocate", JOB)


def test_remoteok_keeps_its_own_platform():
    """У RemoteOK свой канал — с переходом через /l/<id> и распознаванием
    платной стены. Отправлять его на площадку Remocate значит это потерять."""
    url = "https://remoteok.com/remote-jobs/1091234-backend-acme"
    assert detect_contact(url) == Contact("remoteok", url)


def test_a_named_person_still_wins_over_the_board():
    """Живой контакт лучше формы: если в посте есть ник, пишем человеку."""
    text = f"Ищем стажёра, пиши @ivan_hr\n{JOB}"
    assert detect_contact(text).platform == "telegram"


def test_the_link_is_still_the_page_we_read_for_that_lead():
    """И тогда ссылка остаётся адресом, откуда читается описание вакансии."""
    text = f"Ищем стажёра, пиши @ivan_hr\n{JOB}"
    assert pick_vacancy_url(text) == JOB


def test_the_page_counts_as_fetchable():
    assert is_fetchable_vacancy_url(JOB)
    assert is_fetchable_vacancy_url("https://remoteok.com/remote-jobs/1-backend-acme")


def test_a_scheme_less_link_is_found_and_made_absolute():
    text = "смотри remocate.app/jobs/software-engineering-intern-winter-datadog"
    assert list(iter_urls(text)) == [
        "https://remocate.app/jobs/software-engineering-intern-winter-datadog"]


# --- чтение страницы ---------------------------------------------------------

def test_the_vacancy_text_carries_role_company_and_description():
    text = extract_aggregator_vacancy(PAGE)

    assert "Software Engineering Intern" in text
    assert "Datadog" in text
    assert "Junior" in text and "USA" in text
    assert "observability" in text


def test_other_vacancies_further_down_the_page_are_cut_off():
    """Замер: описание кончается на «Apply for this job», ниже идут чужие
    карточки. Без обреза в бриф уезжает вакансия другой компании."""
    text = extract_aggregator_vacancy(PAGE)

    assert "Monetha" not in text
    assert "ЧУЖАЯ" not in text


def test_scripts_never_reach_the_brief():
    assert "ignore me" not in extract_aggregator_vacancy(PAGE)


# --- настоящий адрес отклика -------------------------------------------------

def test_the_single_employer_link_is_found_among_the_noise():
    assert aggregator_apply_url(PAGE, JOB) == APPLY


def test_the_aggregators_own_subdomains_are_not_the_employer():
    """lemonsqueezy и betteruptime — сервисы САМОГО агрегатора, не работодателя."""
    url = aggregator_apply_url(PAGE, JOB)
    assert "lemonsqueezy" not in url and "betteruptime" not in url


def test_ambiguity_is_refused_rather_than_guessed():
    """Тот же принцип, что и у точки входа Easy Apply: несколько кандидатов —
    значит не угадываем, а отдаём пусто и оставляем человеку."""
    page = PAGE.replace("<script>var noise", '<a href="https://jobs.lever.co/other/1">x</a><script>var noise')
    assert aggregator_apply_url(page, JOB) == ""


def test_a_page_without_an_employer_link_returns_empty():
    page = PAGE.replace(APPLY, "https://www.remocate.app/jobs/other")
    assert aggregator_apply_url(page, JOB) == ""


# --- кнопка отклика, а не первая попавшаяся ссылка того же хоста --------------
#
# Замер 2026-08-27, 242 карточки remocate, читанные живьём: кнопка «Apply for
# this job» стоит на всех 242, а правило «единственный внешний хост» выше дало
# верный адрес только на 172. Шестьдесят раз оно промолчало (хостов на странице
# оказывалось несколько), четыре раза увело не туда. Худший из четырёх —
# карточка `director-of-reward-and-people-analytics`: правило вернуло
# `n26.com/en-eu/blog`, потому что блог упомянут в описании на несколько
# килобайт раньше кнопки. Хост единственный, «неоднозначности» нет, и письмо
# писалось бы по блогу.
#
# Разметка ниже снята дословно с этой карточки: те же классы, тот же
# `contact-wrapper` перед кнопкой, тот же `apply-disclaimer` после.

N26_APPLY = "https://n26.com/en-eu/careers/positions/6668071"
N26_PAGE = f"""<!doctype html><html><head>
<title>Director of Reward and People Analytics at N26</title></head><body>
<a href="/blog" class="button is-secondary is-nav w-button">Blog</a>
<a href="https://remocate.lemonsqueezy.com" class="button w-button">Post a job</a>
<h1>Director of Reward and People Analytics</h1>
<p>Technology and design empower <a href="https://n26.com/en-eu/blog">everything we do</a>
and it&#x27;s how we are building the global banking platform.</p>
<p>Read our <a href="https://n26.com/en-eu/diversity-and-inclusion">website</a> to learn more.</p>
<div class="contact-wrapper w-condition-invisible"><div>Contact info:&nbsp;</div>
<a href="#" class="w-dyn-bind-empty"></a></div>
<a href="{N26_APPLY}" class="button w-button">Apply for this job</a>
<div class="apply-disclaimer">Please mention &quot;I found this job at Remocate!&quot;</div>
</body></html>"""
N26_JOB = "https://www.remocate.app/jobs/director-of-reward-and-people-analytics"


def test_the_button_beats_a_link_that_merely_stands_earlier():
    """Ровно тот случай, где прежнее правило отдавало блог N26."""
    assert aggregator_apply_url(N26_PAGE, N26_JOB) == N26_APPLY


def test_the_boards_own_buttons_are_not_the_apply_button():
    """Класс `button w-button` у Webflow носят ВСЕ кнопки сайта — и «Blog», и
    «Post a job». Одного класса мало, поэтому кнопка узнаётся ещё и по надписи."""
    page = N26_PAGE.replace(f'<a href="{N26_APPLY}" class="button w-button">'
                            'Apply for this job</a>', "")
    assert "lemonsqueezy" not in aggregator_apply_url(page, N26_JOB)


def test_an_apply_link_inside_the_description_is_not_the_button():
    """Одной надписи тоже мало: на карточке
    `middle-fullstack-developer-next-js-hono-drizzle-ai-sdk` в тексте стоит
    ссылка «Apply here» на Google Forms, и она не кнопка — у неё нет класса."""
    page = N26_PAGE.replace(
        "<h1>", '<a href="https://forms.gle/wZU1k9ySLjQWwNUPA">Apply here</a><h1>')
    assert aggregator_apply_url(page, N26_JOB) == N26_APPLY


def test_two_employers_on_the_page_no_longer_make_it_ambiguous():
    """Раньше вторая ссылка работодателя обнуляла ответ. Кнопка спор решает: её
    поставил сам агрегатор, а не наш перебор."""
    page = N26_PAGE.replace("<h1>", '<a href="https://jobs.lever.co/other/1">x</a><h1>')
    assert aggregator_apply_url(page, N26_JOB) == N26_APPLY


def test_a_button_without_an_address_means_the_card_has_no_apply_page():
    """`href="#"` — это не «кнопку не нашли». Так Webflow рисует ту же кнопку,
    когда отклик идёт письмом: рядом лежит заполненный `contact-wrapper`. Таких
    карточек 7 из 242, и на одной из них прежнее правило вернуло
    `88publishing.com` — главную страницу компании, где отклика нет вовсе."""
    page = N26_PAGE.replace(f'href="{N26_APPLY}" class="button w-button"',
                            'href="#" class="button w-button"')
    assert aggregator_apply_url(page, N26_JOB) == ""


def test_the_contact_beside_an_empty_button_never_becomes_the_apply_url():
    """Почту и телеграм из `contact-wrapper` открывает не браузер: `page.goto`
    на `mailto:` падает, а маршрут EMAIL начинается уже на странице
    работодателя. Отдать их отсюда как адрес отклика значит сломать оба."""
    page = N26_PAGE.replace(
        '<a href="#" class="w-dyn-bind-empty"></a>',
        '<a href="mailto:zarina@88projects.org">zarina@88projects.org</a>'
        '<a href="https://t.me/tzarina">https://t.me/tzarina</a>')
    page = page.replace(f'href="{N26_APPLY}" class="button w-button"',
                        'href="#" class="button w-button"')
    assert aggregator_apply_url(page, N26_JOB) == ""


def test_a_button_pointing_back_at_the_board_is_not_an_employer():
    page = N26_PAGE.replace(N26_APPLY, "https://www.remocate.app/jobs/other")
    assert aggregator_apply_url(page, N26_JOB) == ""


def test_the_old_single_host_rule_still_answers_when_there_is_no_button():
    """Прежнее правило осталось запасным вариантом, а не выброшено: страница без
    кнопки (другой агрегатор, другая вёрстка) по-прежнему разбирается им."""
    assert aggregator_apply_url(PAGE, JOB) == APPLY
