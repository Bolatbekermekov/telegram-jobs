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
