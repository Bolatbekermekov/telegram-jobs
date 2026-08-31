"""Разбор ленты remocate.app. Разметка снята с живой страницы 2026-08-27.

Фикстуры ниже — не выдумка: это сокращённые до одного-двух объявлений куски
`https://www.remocate.app/job-categories/development` (Webflow + Finsweet), с
сохранением ВСЕХ атрибутов, по которым идёт разбор. Значения — настоящие.
"""
from app.domain.candidate import KIND_JOB, normalize_url
from app.infrastructure.search.remocate_search import (
    DEFAULT_HOME_PAGES, DEFAULT_PAGES, REMOCATE_HOME_URL, RemocateSearcher,
    next_page_url, parse_remocate_cards, strip_html, to_candidate,
    DEFAULT_QA_PAGES,
)

FEED = "https://www.remocate.app/job-categories/development"
HOME = "https://www.remocate.app/"


def _card(slug, title, company, location="🌎 World", salary="$115,000 – $195,500",
          desc="<p>We use <b>Go</b> and Postgres.</p>") -> str:
    """Одна карточка живой ленты. Порядок и имена атрибутов — как на сайте."""
    return (
        '<div role="listitem" class="w-dyn-item">'
        f'<a href="/jobs/{slug}" class="job-card w-inline-block">'
        '<div class="job-card-left"><img class="job-logo"/>'
        '<div class="job-card-content"><div class="job-card-top">'
        f'<div fs-cmsfilter-field="name" class="job-title">{title}</div>'
        '<div class="job-card-divider">•</div>'
        f'<div fs-cmsfilter-field="company">{company}</div></div>'
        '<div class="job-cards">'
        '<div fs-cmsfilter-field="employment" class="job-card-bubble hidden">Full-time</div>'
        f'<div fs-cmsfilter-field="location" class="job-card_tag">{location}</div>'
        '<div fs-cmsfilter-field="category" class="job-card_tag">💻 Development</div>'
        f'<div fs-cmssort-field="salary" class="job-card-bubble hidden">{salary}</div>'
        '<div fs-cmsfilter-field="location" class="job-card-bubble hidden">📍 Any Location</div>'
        '<div fs-cmsfilter-field="type" class="job-card_tag">🏠 Remote</div>'
        '</div></div></div>'
        '<div class="job-card-right"><div class="job-date home-date">Aug 26, 2026</div></div>'
        '</a>'
        f'<div fs-cmsfilter-field="description" class="job-card-desc w-richtext">{desc}</div>'
        '</div>'
    )


def _page(cards, next_page="?c74bbb03_page=2") -> str:
    """Страница ленты: список карточек и блок листалки Webflow.

    Хвост после списка настоящий и важен: там сидят ЧУЖИЕ `w-dyn-item` (подвал
    со списком категорий), у которых нет ссылки на вакансию. Разбор обязан их
    пропускать, а не падать на отсутствующем заголовке.
    """
    nav = (
        '<div role="navigation" aria-label="List" class="w-pagination-wrapper hidden">'
        '<a href="?c74bbb03_page=1" aria-label="Previous Page" class="w-pagination-previous">'
        '<div class="w-inline-block">Previous</div></a>'
        + (f'<a href="{next_page}" aria-label="Next Page" class="w-pagination-next">'
           '<div class="w-inline-block">Next</div>'
           '<svg class="w-pagination-next-icon"></svg></a>' if next_page else "")
        + '<div aria-label="Page 1 of 102" role="heading" class="w-page-count">1 / 102</div>'
        '</div>'
    )
    footer = ('<div class="footer_wrapper"><div role="list" class="w-dyn-items">'
              '<div role="listitem" class="w-dyn-item">'
              '<a href="/job-categories/design" class="w-inline-block">Design</a>'
              '</div></div></div>')
    return ('<div role="list" class="board-list w-dyn-items">'
            + "".join(cards) + "</div>" + nav + footer)


# --- разбор карточки --------------------------------------------------------

QA = "https://www.remocate.app/job-categories/qa"


def test_parse_reads_title_company_url_and_location():
    cards = parse_remocate_cards(_page([
        _card("senior-backend-engineer-nodejs-bluethrone",
              "Senior Backend Engineer (Node.js)", "BlueThrone"),
    ]))

    assert len(cards) == 1
    job = cards[0]
    assert job["title"] == "Senior Backend Engineer (Node.js)"
    assert job["company"] == "BlueThrone"
    assert job["location"] == "🌎 World"
    # Ссылка на карточке относительная — в лид обязана попасть абсолютная, той
    # же формы, что уже лежит в листе: contact.py узнаёт вакансию по
    # `remocate.app/jobs/<slug>`, а канал отправки выбирается по ней.
    assert job["url"] == ("https://www.remocate.app/jobs/"
                          "senior-backend-engineer-nodejs-bluethrone")


def test_parse_skips_items_that_are_not_job_cards():
    # Подвал страницы — такие же `w-dyn-item`, но ведут на категорию, а не на
    # вакансию. Их на живой странице 15 штук против 20 настоящих карточек.
    assert parse_remocate_cards(_page([])) == []


def test_parse_takes_the_description_from_the_listing():
    """Описание лежит прямо в ленте — второй запрос за ним не нужен.

    Проверено живьём 2026-08-27: у карточки Chess.com в ленте 4531 символ
    разметки описания против 4519 на самой странице вакансии, текст совпадает.
    Это и есть причина, по которой describe() ничего не качает.
    """
    cards = parse_remocate_cards(_page([
        _card("x", "Backend Developer", "Acme",
              desc="<p>We use <b>Go</b> and Postgres.</p>"),
    ]))
    assert cards[0]["description"] == "We use Go and Postgres."


def test_parse_unescapes_html_entities():
    # На живой странице такое встретилось: «Head of Applied Science &amp;
    # Engineering». Без раскодировки амперсанд уехал бы в письмо как есть.
    cards = parse_remocate_cards(_page([
        _card("y", "Head of Applied Science &amp; Engineering", "Bol&#x27;s"),
    ]))
    assert cards[0]["title"] == "Head of Applied Science & Engineering"
    assert cards[0]["company"] == "Bol's"


def test_a_card_without_a_location_tag_is_still_a_job():
    """У самых старых объявлений тега страны нет вовсе.

    Живой замер 2026-08-27, последняя страница ленты (102/102): у 4 карточек из
    13 поле location пустое — заголовок, компания и описание при этом на месте.
    Пустая локация не пишет в бриф пустую подпись «Локация: .»
    (search_leads_repo._vacancy_text), поэтому терять из-за неё вакансию незачем.
    """
    card = _card("old", "Frontend Developer", "12Go Asia").replace(
        '<div fs-cmsfilter-field="location" class="job-card_tag">🌎 World</div>', "")
    cards = parse_remocate_cards(_page([card]))

    assert len(cards) == 1
    assert cards[0]["location"] == ""
    assert to_candidate(cards[0]).title == "Frontend Developer"


def test_parse_reads_the_country_flag_location_as_is():
    cards = parse_remocate_cards(_page([
        _card("z", "Backend Developer", "Acme", location="🇩🇪 Germany"),
    ]))
    assert cards[0]["location"] == "🇩🇪 Germany"


def test_salary_is_read_but_kept_out_of_the_candidate():
    """Вилка на карточке — ОЦЕНКА САЙТА, а не число работодателя.

    Замер 2026-08-27 по 60 карточкам первых трёх страниц: значение лежит в
    `<div class="job-card-bubble hidden">`, то есть человеку сайт его не
    показывает вовсе; на странице самой вакансии зарплаты нет ни в каком виде;
    а сами значения кластеризуются строго по слову уровня в заголовке — одна и
    та же вилка «$115,000 – $195,500» стоит у всех 16 карточек со словом
    Senior, «$80,500 – $138,000» — у 13 остальных.

    Поэтому поле разбирается (чтобы находка была видна и не потерялась), но в
    `Candidate.salary` НЕ уезжает: оттуда оно попало бы строкой «Зарплата: …» в
    бриф, по которому пишется письмо, и модель сослалась бы работодателю на
    вилку, которую тот никогда не публиковал.
    """
    job = parse_remocate_cards(_page([_card("q", "Backend Developer", "Acme")]))[0]
    assert job["salary_estimate"] == "$115,000 – $195,500"
    assert to_candidate(job).salary == ""


def test_to_candidate_maps_the_platform_name_the_sheet_already_uses():
    # Имя площадки — `remocate`, ровно как у уже существующих лидов: по нему
    # выбирается канал отправки (channels/registry.py) и по нему же работает
    # выключатель PAUSED_PLATFORMS.
    job = parse_remocate_cards(_page([
        _card("a", "Backend Developer", "Acme", location="🇵🇱 Poland")]))[0]
    c = to_candidate(job)
    assert c.platform == "remocate"
    assert c.kind == KIND_JOB
    assert c.title == "Backend Developer"
    assert c.company == "Acme"
    assert c.location == "🇵🇱 Poland"
    assert c.summary == ""      # заполнит скоринг релевантности


def test_strip_html():
    assert strip_html("<p>We use <b>Go</b> and Postgres.</p>") == "We use Go and Postgres."


def test_strip_html_puts_a_space_where_a_tag_was():
    """Тег становится пробелом, а не пустотой — как у RemoteOK и Remotive.

    Цена известна: перед точкой после «</b>» остаётся пробел. Плата за
    обратное больше — соседние абзацы «</p><p>» склеились бы в одно слово, а
    текст этот читает скорер релевантности.
    """
    assert strip_html("<p>Go and <b>Kubernetes</b>.</p><p>Remote.</p>") \
        == "Go and Kubernetes . Remote."


# --- листалка ---------------------------------------------------------------

def test_next_page_url_is_resolved_against_the_current_one():
    # Имя параметра содержит хеш коллекции Webflow (`c74bbb03_page`), который
    # меняется при пересборке сайта. Поэтому ссылка берётся со страницы, а не
    # собирается нами.
    assert next_page_url(_page([]), FEED) == FEED + "?c74bbb03_page=2"


def test_next_page_url_is_empty_on_the_last_page():
    # Живая страница 102/102: блок листалки есть, ссылки «Next» в нём нет.
    assert next_page_url(_page([], next_page=""), FEED) == ""


# --- поиск ------------------------------------------------------------------

class _Feed:
    """Лента-заглушка: отдаёт заранее собранные страницы и считает запросы."""

    def __init__(self, pages):
        self.pages = pages
        self.requested = []

    def __call__(self, url):
        self.requested.append(url)
        return self.pages[len(self.requested) - 1]


def _feed(base, pages_cards, page_hash) -> dict:
    """Лента как {адрес: разметка} — для проверок, где лент ДВЕ.

    Хеш листалки у каждой ленты свой: у раздела `c74bbb03_page`, у главной
    `ee7bb4b9_page` (снято с живых страниц 2026-08-27). Он и меняется при
    пересборке сайта, поэтому парсер обязан брать ссылку со страницы, а не
    собирать её сам — здесь это проверяется тем, что хеши разные.
    """
    out = {}
    for i, cards in enumerate(pages_cards):
        url = base if i == 0 else f"{base}?{page_hash}_page={i + 1}"
        nxt = f"?{page_hash}_page={i + 2}" if i + 1 < len(pages_cards) else ""
        out[url] = _page(cards, next_page=nxt)
    return out


class _Site:
    """Сайт-заглушка: несколько лент сразу, ответ по адресу, порядок запросов."""

    def __init__(self, *feeds):
        self.pages = {}
        for f in feeds:
            self.pages.update(f)
        self.requested = []

    def __call__(self, url):
        self.requested.append(url)
        return self.pages[url]


def test_search_walks_pages_and_stops_at_the_configured_depth():
    """Глубина — это ответ на замер, а не круглое число.

    Доля мёртвых вакансий по страницам ленты — сплошная проверка 2026-08-27 всех
    200 карточек первых десяти страниц тем же `vacancy_alive`, что стоит в
    прогоне: 1-я 20%, 2-я 35%, 3-я 25%, 4-я 20%, 5-я 20%, 6-я 55%, 7-я 60%,
    8-я 40%, 9-я 35%, 10-я 70%. Четвёртая и пятая живы ровно как первая, обрыв
    начинается с шестой, поэтому по умолчанию берутся первые пять страниц.
    """
    feed = _Feed([
        _page([_card("p1", "Backend Developer", "A")], next_page="?c74bbb03_page=2"),
        _page([_card("p2", "Frontend Developer", "B")], next_page="?c74bbb03_page=3"),
        _page([_card("p3", "QA Engineer", "C")], next_page="?c74bbb03_page=4"),
    ])
    s = RemocateSearcher(feed_url=FEED, qa_url="", home_url="", pages=2)
    s._page = feed

    found = s.search(["backend developer", "frontend developer", "qa engineer"],
                     "Worldwide", limit=50)

    assert [c.title for c in found] == ["Backend Developer", "Frontend Developer"]
    assert feed.requested == [FEED, FEED + "?c74bbb03_page=2"]


def test_search_stops_when_the_feed_runs_out_of_pages():
    feed = _Feed([_page([_card("p1", "Backend Developer", "A")], next_page="")])
    s = RemocateSearcher(feed_url=FEED, qa_url="", home_url="", pages=5)
    s._page = feed

    assert len(s.search(["backend developer"], "Worldwide", limit=50)) == 1
    assert feed.requested == [FEED]


def test_search_filters_by_role_words_in_the_title():
    # Тот же предфильтр, что у RemoteOK и Remotive (app.domain.keyword_match):
    # уровень («Senior», «Lead») он не трогает — за уровень отвечает скоринг.
    feed = _Feed([_page([
        _card("a", "Senior Backend Engineer", "A"),
        _card("b", "Senior Scrum Master", "B"),
    ], next_page="")])
    s = RemocateSearcher(feed_url=FEED, qa_url="", home_url="", pages=1)
    s._page = feed

    found = s.search(["backend developer"], "Worldwide", limit=50)
    assert [c.title for c in found] == ["Senior Backend Engineer"]


def test_search_does_not_repeat_a_job_that_slid_to_the_next_page():
    """Одна вакансия — одна карточка, даже если лента сдвинулась под нами.

    Страницы качаются последовательно, и новое объявление, опубликованное между
    двумя запросами, сдвигает вниз всё остальное: карточка с первой страницы
    приезжает второй раз уже со второй. Дедупликация в листе от этого не
    спасает — она сравнивает с УЖЕ СОХРАНЁННЫМИ строками, а два одинаковых URL
    внутри одной выдачи для неё оба новые.
    """
    slid = _card("p1", "Backend Developer", "A")
    feed = _Feed([
        _page([slid], next_page="?c74bbb03_page=2"),
        _page([slid, _card("p2", "QA Engineer", "B")], next_page=""),
    ])
    s = RemocateSearcher(feed_url=FEED, qa_url="", home_url="", pages=3)
    s._page = feed

    found = s.search(["backend developer", "qa engineer"], "Worldwide", limit=50)
    assert [c.url for c in found] == [
        "https://www.remocate.app/jobs/p1", "https://www.remocate.app/jobs/p2"]


def test_search_honours_the_limit():
    feed = _Feed([_page([
        _card("a", "Backend Developer", "A"),
        _card("b", "Backend Developer", "B"),
    ], next_page="")])
    s = RemocateSearcher(feed_url=FEED, qa_url="", home_url="", pages=3)
    s._page = feed

    assert len(s.search(["backend developer"], "Worldwide", limit=1)) == 1


def test_describe_serves_the_cached_listing_description():
    feed = _Feed([_page([
        _card("a", "Backend Developer", "A",
              desc="<p>Go and <b>Postgres</b> in production.</p>"),
    ], next_page="")])
    s = RemocateSearcher(feed_url=FEED, qa_url="", home_url="", pages=1)
    s._page = feed
    s.search(["backend developer"], "Worldwide", limit=50)

    assert s.describe("https://www.remocate.app/jobs/a") == "Go and Postgres in production."
    assert len(feed.requested) == 1     # describe() ничего не качает


def test_describe_is_empty_for_an_unknown_url():
    assert RemocateSearcher().describe("https://www.remocate.app/jobs/nope") == ""


def test_search_starts_from_a_clean_cache_every_run():
    # Воркер держит searcher между прогонами: без очистки кэш описаний рос бы
    # весь день и отдавал бы текст вакансии, которой в сегодняшней ленте нет.
    s = RemocateSearcher(feed_url=FEED, qa_url="", home_url="", pages=1)
    s._page = _Feed([_page([_card("a", "Backend Developer", "A")], next_page="")])
    s.search(["backend developer"], "Worldwide", limit=50)
    s._page = _Feed([_page([_card("b", "QA Engineer", "B")], next_page="")])
    s.search(["qa engineer"], "Worldwide", limit=50)

    assert s.describe("https://www.remocate.app/jobs/a") == ""


def test_search_keeps_what_it_already_collected_when_a_page_fails():
    """Обрыв на третьей странице не должен обнулять первые две.

    У соседей (RemoteOK, Remotive) вся выдача — один запрос, и там «упало =
    пусто» равнозначно. Здесь запросов несколько, и терять уже собранное из-за
    последнего было бы дороже.
    """
    def feed(url):
        if url == FEED:
            return _page([_card("a", "Backend Developer", "A")],
                         next_page="?c74bbb03_page=2")
        raise RuntimeError("503 Service Unavailable")

    s = RemocateSearcher(feed_url=FEED, qa_url="", home_url="", pages=3)
    s._page = feed

    assert [c.title for c in s.search(["backend developer"], "Worldwide", limit=50)] \
        == ["Backend Developer"]


def test_search_survives_the_very_first_page_failing():
    def boom(url):
        raise RuntimeError("timeout")

    s = RemocateSearcher(feed_url=FEED, qa_url="", home_url="", pages=3)
    s._page = boom
    assert s.search(["backend developer"], "Worldwide", limit=50) == []


def test_zero_pages_falls_back_to_the_default_depth():
    """Опечатка в .env не должна превратить узкую ленту в обход кладбища.

    В соседних настройках ноль значит «ограничения нет» (см.
    search_request.per_keyword_limit), и здесь такое правило было бы вредным: в
    ленте 102 страницы, а живой запас — первые пять. Пустое или нулевое значение
    возвращает умолчание.
    """
    feed = _Feed([_page([_card(f"p{i}", "Backend Developer", "A"),],
                        next_page=f"?c74bbb03_page={i + 1}") for i in range(1, 8)])
    s = RemocateSearcher(feed_url=FEED, qa_url="", home_url="", pages=0)
    s._page = feed
    s.search(["backend developer"], "Worldwide", limit=50)

    assert len(feed.requested) == DEFAULT_PAGES == 5


def test_start_stop_are_noops():
    s = RemocateSearcher(qa_url="")
    s.start()
    s.stop()   # ни браузера, ни сессии — страницы публичные


# --- второй проход: главная -------------------------------------------------
#
# Разделов у remocate 15, и вакансия лежит РОВНО в одном: попарные пересечения
# выкачанных целиком разделов равны нулю (замер 2026-08-27, вся лента — 273
# страницы, 5459 карточек). Значит раздел `development` физически не может
# показать вакансию, которую в него не положили. Хуже того, у части объявлений
# поле категории в CMS пустое вовсе, и такие видны ТОЛЬКО на главной: из первых
# 60 карточек главной у 12 нет видимого тега категории, четыре из них проходят
# предфильтр — Senior Security Engineer (Scorewarrior), AI Search Visibility
# Specialist, Community / Social Media Manager, AI Motion Designer.

def test_the_home_page_is_walked_as_a_second_shallower_pass():
    """Главная — ДОПОЛНЕНИЕ к разделу, а не замена ему, и идёт после него.

    При равном бюджете запросов раздел даёт вдвое больше (замер 2026-08-27, те
    же 14 слов из SEARCH_KEYWORDS): 5 страниц development — 100 карточек, 79
    прошли предфильтр; 5 страниц главной — те же 100 карточек, но прошли 35, и
    только 8 из них не встретились в development. Поэтому глубокий проход —
    раздел, а главная снимает лишь верхушку.
    """
    site = _Site(
        _feed(FEED, [[_card("d1", "Backend Developer", "A")],
                     [_card("d2", "Frontend Developer", "B")],
                     [_card("d3", "QA Engineer", "C")]], "c74bbb03"),
        _feed(HOME, [[_card("h1", "Python Developer", "D")],
                     [_card("h2", "Mobile Developer", "E")],
                     [_card("h3", "AI Engineer", "F")]], "ee7bb4b9"),
    )
    s = RemocateSearcher(feed_url=FEED, qa_url="", pages=2, home_url=HOME, home_pages=1)
    s._page = site

    found = s.search(["backend developer", "frontend developer", "qa engineer",
                      "python developer", "mobile developer", "ai engineer"],
                     "Worldwide", limit=50)

    assert [c.title for c in found] == [
        "Backend Developer", "Frontend Developer", "Python Developer"]
    assert site.requested == [FEED, FEED + "?c74bbb03_page=2", HOME]


def test_a_job_the_section_already_gave_is_not_taken_again_from_the_home_page():
    """Главная показывает и то, что лежит в разделах, — дедуп общий на оба прохода.

    Замер 2026-08-27: из 100 карточек первых пяти страниц главной 30 уже стояли
    в первых пяти страницах раздела development (на трёх страницах — 15 из 60).
    Без общего `seen` каждая такая вакансия заняла бы второй слот в бюджете
    скоринга и стоила бы второго вызова модели: дедупликация в листе не спасает,
    она сравнивает с СОХРАНЁННЫМИ строками, а два одинаковых URL внутри одной
    выдачи для неё оба новые.
    """
    both = _card("shared", "Backend Developer", "Acme")
    site = _Site(
        _feed(FEED, [[both, _card("d2", "QA Engineer", "B")]], "c74bbb03"),
        _feed(HOME, [[both, _card("h2", "Mobile Developer", "C")]], "ee7bb4b9"),
    )
    s = RemocateSearcher(feed_url=FEED, qa_url="", pages=1, home_url=HOME, home_pages=1)
    s._page = site

    found = s.search(["backend developer", "qa engineer", "mobile developer"],
                     "Worldwide", limit=50)

    assert [c.url for c in found] == [
        "https://www.remocate.app/jobs/shared",
        "https://www.remocate.app/jobs/d2",
        "https://www.remocate.app/jobs/h2",
    ]


def test_the_home_pass_caches_its_descriptions_like_the_section_one():
    # describe() отвечает из кэша ленты, и вакансия с главной не должна быть
    # исключением — иначе скорер получил бы пустое описание и оценил заголовок.
    orphan = _card("h1", "AI Engineer", "B",
                   desc="<p>We run PyTorch and <b>Triton</b></p>")
    site = _Site(
        _feed(FEED, [[_card("d1", "Backend Developer", "A")]], "c74bbb03"),
        _feed(HOME, [[orphan]], "ee7bb4b9"),
    )
    s = RemocateSearcher(feed_url=FEED, qa_url="", pages=1, home_url=HOME, home_pages=1)
    s._page = site
    s.search(["backend developer", "ai engineer"], "Worldwide", limit=50)

    assert s.describe("https://www.remocate.app/jobs/h1") == "We run PyTorch and Triton"
    assert len(site.requested) == 2     # describe() ничего не качает


def test_the_home_pass_still_runs_when_the_section_feed_breaks():
    """Обрыв раздела не отменяет главную — это РАЗНЫЕ ленты.

    Бесхозные вакансии (поле категории в CMS пустое) видны только здесь, и
    503-я на второй странице раздела не повод их не смотреть.
    """
    home = _feed(HOME, [[_card("h1", "AI Engineer", "B")]], "ee7bb4b9")

    def flaky(url):
        if url == HOME:
            return home[HOME]
        raise RuntimeError("503 Service Unavailable")

    s = RemocateSearcher(feed_url=FEED, qa_url="", pages=3, home_url=HOME, home_pages=1)
    s._page = flaky

    found = s.search(["backend developer", "ai engineer"], "Worldwide", limit=50)
    assert [c.title for c in found] == ["AI Engineer"]


def test_the_limit_is_one_budget_for_both_passes():
    # `limit` — потолок на площадку за прогон (SEARCH_LIMIT_PER_PLATFORM=250), а
    # не на ленту. Если его выбрал раздел, за главной идти уже не на что.
    site = _Site(
        _feed(FEED, [[_card("d1", "Backend Developer", "A"),
                      _card("d2", "QA Engineer", "B")]], "c74bbb03"),
        _feed(HOME, [[_card("h1", "AI Engineer", "C")]], "ee7bb4b9"),
    )
    s = RemocateSearcher(feed_url=FEED, qa_url="", pages=1, home_url=HOME, home_pages=1)
    s._page = site

    found = s.search(["backend developer", "qa engineer", "ai engineer"],
                     "Worldwide", limit=2)

    assert [c.title for c in found] == ["Backend Developer", "QA Engineer"]
    assert site.requested == [FEED]     # до главной бюджет не дожил


def test_zero_home_pages_falls_back_to_the_default_home_depth():
    """Правило то же, что у REMOCATE_PAGES: ноль и пусто = умолчание.

    Две настройки глубины стоят в .env соседними строками, и разное значение
    нуля у них было бы ловушкой. Три страницы главной — это ответ на замер
    2026-08-27: новых (не виданных разделом) карточек, прошедших предфильтр,
    первая страница даёт 3, вторая +2, третья +2, ЧЕТВЁРТАЯ +0, пятая +1.
    """
    site = _Site(
        _feed(FEED, [[_card("d1", "Backend Developer", "A")]], "c74bbb03"),
        _feed(HOME, [[_card(f"h{i}", "Backend Developer", "B")]
                     for i in range(1, 7)], "ee7bb4b9"),
    )
    s = RemocateSearcher(feed_url=FEED, qa_url="", pages=1, home_url=HOME, home_pages=0)
    s._page = site
    s.search(["backend developer"], "Worldwide", limit=50)

    assert len(site.requested) == 1 + DEFAULT_HOME_PAGES
    assert DEFAULT_HOME_PAGES == 3


def test_the_default_second_pass_is_the_site_root():
    # Главная — это буквально корень сайта, а не ещё один раздел: своей
    # настройки адреса у неё нет и указывать её некуда.
    assert REMOCATE_HOME_URL == "https://www.remocate.app/"
    s = RemocateSearcher(feed_url=FEED, qa_url="", pages=1)
    site = _Site(_feed(FEED, [[_card("d1", "Backend Developer", "A")]], "c74bbb03"),
                 _feed(REMOCATE_HOME_URL,
                       [[_card("h1", "AI Engineer", "B")]], "ee7bb4b9"))
    s._page = site
    s.search(["backend developer", "ai engineer"], "Worldwide", limit=50)

    assert site.requested[1] == REMOCATE_HOME_URL


# --- оценка релевантности ---------------------------------------------------
#
# В ленте полно Principal / Lead / Senior / Manager: из 60 карточек первых трёх
# страниц (замер 2026-08-27) предфильтр по словам роли пропускает 49, и уровень
# он не смотрит вовсе — слова уровня из ключевого слова выбрасываются
# (app.domain.keyword_match). Отсеивает их скоринг, тот же самый, что у
# остальных площадок; своего отбора по уровню здесь нет и быть не должно.

class _Repo:
    def __init__(self, known=()):
        self.added = []
        self._known = {normalize_url(u) for u in known}

    def known_urls(self):
        return set(self._known)

    def add_new(self, candidates):
        self.added += list(candidates)
        return len(self.added)


class _LevelScorer:
    """Скорер-заглушка в духе search_profile.txt: senior/lead/principal — мимо."""

    def __init__(self):
        self.seen = []

    def score(self, profile, title, description, location=""):
        self.seen.append((title, description))
        junk = ("senior", "lead", "principal", "staff", "manager")
        return (20, "уровень выше") if any(w in title.lower() for w in junk) \
            else (85, "подходит по стеку")


def test_found_jobs_go_through_the_same_relevance_scoring_as_other_boards():
    from app.application.run_search import run_search

    feed = _Feed([_page([
        _card("a", "Principal Software Engineer", "Zalando"),
        _card("b", "Backend Developer", "Acme", desc="<p>Go, Postgres.</p>"),
    ], next_page="")])
    s = RemocateSearcher(feed_url=FEED, qa_url="", home_url="", pages=1)
    s._page = feed
    repo = _Repo()

    added = run_search(["remocate"], {"remocate": s}, repo,
                       keywords=["backend developer"], location="Worldwide",
                       limit=50, scorer=_LevelScorer(), profile="p",
                       threshold=60, max_jobs=30)

    assert added == 1
    kept = repo.added[0]
    assert kept.title == "Backend Developer"
    # Оценка приклеивается к кандидату тем же кодом, что у соседей.
    assert kept.summary == "85/100: подходит по стеку"


def test_a_job_already_in_the_sheet_is_not_scored_again():
    """Лид remocate в листе уже есть (16 штук на 2026-08-27) — платить за него
    второй раз нельзя.

    Своего дедупа searcher не заводит: он отдаёт кандидата с той же формой
    адреса, что лежит в колонке «Источник» (`https://www.remocate.app/jobs/…`),
    а дальше работает общая машинерия — `run_search` спрашивает у листа
    known_urls() ДО скоринга, чтобы не тратить вызов модели на дубль.
    """
    from app.application.run_search import run_search

    known = "https://www.remocate.app/jobs/software-engineering-intern-winter-datadog"
    feed = _Feed([_page([
        _card("software-engineering-intern-winter-datadog", "Backend Developer",
              "Datadog"),
        _card("b", "QA Engineer", "Acme"),
    ], next_page="")])
    s = RemocateSearcher(feed_url=FEED, qa_url="", home_url="", pages=1)
    s._page = feed
    scorer = _LevelScorer()

    run_search(["remocate"], {"remocate": s}, _Repo(known=[known]),
               keywords=["backend developer", "qa engineer"], location="Worldwide",
               limit=50, scorer=scorer, profile="p", threshold=60, max_jobs=30)

    assert [t for t, _ in scorer.seen] == ["QA Engineer"]


def test_the_scorer_reads_the_listing_description_without_extra_requests():
    from app.application.run_search import run_search

    feed = _Feed([_page([
        _card("b", "Backend Developer", "Acme",
              desc="<p>Go, Postgres and <b>Kubernetes</b> here.</p>")], next_page="")])
    s = RemocateSearcher(feed_url=FEED, qa_url="", home_url="", pages=1)
    s._page = feed
    scorer = _LevelScorer()

    run_search(["remocate"], {"remocate": s}, _Repo(),
               keywords=["backend developer"], location="Worldwide", limit=50,
               scorer=scorer, profile="p", threshold=60, max_jobs=30)

    assert scorer.seen == [("Backend Developer", "Go, Postgres and Kubernetes here.")]
    assert len(feed.requested) == 1     # одна страница ленты, и ничего сверх неё


# --- язык письма ------------------------------------------------------------

def test_the_written_row_keeps_our_labels_but_stays_english():
    """Русская подпись «Локация: …» не должна голосовать за язык письма.

    Ровно эту болезнь чинили 2026-08-27 (message_language._OWN_LABEL_LINE):
    английская вакансия получала русское письмо из-за НАШЕЙ же разметки. У
    remocate локация выглядит как «🇩🇪 Germany» — кириллицы в значении нет, но
    подпись перед ним русская, и без выбрасывания строки короткий заголовок
    вроде «QA Engineer — Acme» перевесить её не смог бы.
    """
    from app.domain.lead import COLUMNS
    from app.domain.message_language import detect_language
    from app.infrastructure.search_leads_repo import candidate_to_lead_row

    job = parse_remocate_cards(_page([
        _card("a", "QA Engineer", "Acme", location="🇩🇪 Germany")]))[0]
    c = to_candidate(job)
    c.summary = "78/100: подходит по стеку и уровню"
    vacancy = candidate_to_lead_row(c, row_id=1, now="2026-08-27 12:00")[
        COLUMNS.index("Вакансия")]

    assert "Локация: 🇩🇪 Germany" in vacancy, "подпись читает человек — она остаётся"
    assert detect_language(vacancy) == "en"


# --- раздел QA: третья лента, которой в development нет ----------------------
#
# Замер 2026-08-29: 20 карточек, 19 проходят предфильтр, и НИ ОДНА не
# встречается в development. Это отменяет прежнюю запись «в qa ничего свежее
# 21 мая». Мёртвых там 63-68% против 20% в development — цена названа в
# докстринге REMOCATE_QA_URL.

def test_the_qa_section_is_walked_after_development_and_before_the_home():
    feed = _Feed([
        _page([_card("be-1", "Backend Developer", "Acme")], next_page=""),
        _page([_card("qa-2", "QA Engineer", "White Circle")], next_page=""),
        _page([_card("fe-3", "Frontend Developer", "Foxible")], next_page=""),
    ])
    s = RemocateSearcher(feed_url=FEED, pages=1, qa_url=QA, qa_pages=1,
                         home_url=HOME, home_pages=1)
    s._page = feed
    found = s.search(["developer", "qa", "engineer"], "Worldwide", limit=50)

    assert feed.requested == [FEED, QA, HOME]
    assert [c.title for c in found] == [
        "Backend Developer", "QA Engineer", "Frontend Developer"]


def test_the_qa_section_can_be_turned_off_by_an_empty_url():
    feed = _Feed([
        _page([_card("be-1", "Backend Developer", "Acme")], next_page=""),
        _page([_card("fe-3", "Frontend Developer", "Foxible")], next_page=""),
    ])
    s = RemocateSearcher(feed_url=FEED, pages=1, qa_url="",
                         home_url=HOME, home_pages=1)
    s._page = feed
    s.search(["developer"], "Worldwide", limit=50)

    assert feed.requested == [FEED, HOME]


def test_zero_qa_pages_falls_back_to_the_default_depth():
    """Ноль значит «умолчание», как у двух соседних глубин, а не «без предела»."""
    s = RemocateSearcher(feed_url=FEED, qa_url=QA, qa_pages=0, home_url="")
    assert (QA, DEFAULT_QA_PAGES) in s._passes


def test_a_vacancy_seen_in_development_is_not_taken_again_from_qa():
    """`seen` один на все проходы — иначе повтор занял бы второй слот скоринга."""
    same = _card("qa-9", "Fullstack QA Engineer", "Apicworld")
    feed = _Feed([_page([same], next_page=""), _page([same], next_page="")])
    s = RemocateSearcher(feed_url=FEED, pages=1, qa_url=QA, qa_pages=1, home_url="")
    s._page = feed
    found = s.search(["qa", "engineer"], "Worldwide", limit=50)

    assert feed.requested == [FEED, QA]      # обе ленты опрошены
    assert len(found) == 1                   # но вакансия взята один раз
