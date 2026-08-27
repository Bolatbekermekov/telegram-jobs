"""Remocate searcher over the public feeds (no browser, no login).

Remocate — агрегатор: своих вакансий у него нет, он пересобирает чужие, а
отклик живёт на сайте работодателя (канал под это уже есть —
channels/external.py под именем `remocate`). Отсюда особенности разбора, все
снятые с живых страниц 2026-08-27.

ЛЕНТ ДВЕ, и вторая не роскошь. Разделов у сайта 15, и вакансия лежит РОВНО в
одном: попарные пересечения выкачанных целиком разделов равны нулю (замер по
всей ленте — 273 страницы, 5459 карточек). То есть раздел `development`
физически не может показать вакансию, которую в него не положили. Хуже того, у
102 объявлений поле категории в CMS пустое вовсе, и они видны ТОЛЬКО на главной
`https://www.remocate.app/`; за 90 дней таких 57, и среди них профильные роли —
Senior Data Engineer, QA Engineer (Data Stack), Java Backend Developer, Senior
React Native Developer, DevOps Engineer, Senior AI/ML Scientist.

Но главная — ДОПОЛНЕНИЕ, а не замена: при равном бюджете запросов раздел даёт
вдвое больше. Замер теми же 14 словами из SEARCH_KEYWORDS: 5 страниц
development — 100 карточек, 79 прошли предфильтр; 5 страниц главной — те же 100
карточек, но прошли 35, и лишь 8 из них не встретились в development. Поэтому
глубокий проход — раздел (REMOCATE_PAGES=5), а главная снимает верхушку
(REMOCATE_HOME_PAGES=3) и идёт ВТОРОЙ: общий бюджет `limit` должен доставаться
сначала более плотной ленте.

Три страницы главной — не круглое число, а две границы сразу. Первая — отдача:
новых, не виданных разделом карточек, прошедших предфильтр, первая страница
даёт 3, вторая +2, третья +2, ЧЕТВЁРТАЯ +0, пятая +1. Вторая — окно по датам:
главная мешает все 15 разделов и потому проедает календарь вчетверо быстрее
(5 страниц development дотягиваются до 16 июля, 3 страницы главной — только до
21 августа, 5 страниц — до 17 августа). Шесть дней с запасом перекрывают
воркер, который ищет ~3 раза в сутки, — бесхозная вакансия успеет попасться.

Раздел `manager` НЕ добавлен, хотя он живой (1.73 новых вакансии в сутки,
свежайшая — сегодня). Живой он не теми ролями: из 160 его карточек (8 страниц)
слово «engineer» стоит РОВНО в одном заголовке — «Product Engineer (On-site in
NYC)», то есть не удалёнка и профилю не подходит, — и «developer» ровно в одном,
«Director of Global Developer Success». Предфильтр при этом пропускает 14 из
160, все на широких словах («ai», «mobile», «automation»): Product Manager,
Staff Product Manager, Growth Product Manager, Game Presenter. Это те самые 14
оценок ради нуля инженерных вакансий — сделка, от которой уже отказались в
`title_matches` (см. mem:tasks/search-yield-backlog, п. 13). Разделы `qa`,
`analytics`, `support`, `ux-ui`, `smm`, `pr` не добавлены по другой причине —
ноль новых вакансий за 90 дней, кладбище (в `qa` их 200, но ничего свежее
21 мая: новые QA-роли теперь кладут в `development`).

Sitemap брать НЕЛЬЗЯ. `https://www.remocate.app/sitemap.xml` отдаёт
5049 ссылок, и случайная выборка из них показала 65% мёртвых вакансий — до
отправки дошла бы одна из сорока (2,5%). Берётся лента раздела
`/job-categories/development`: на первой странице мёртвых 15%, откликнуться
удалось бы 8 из 20. Живой лист подтверждает это независимо: из 16 лидов
remocate отправлено 4.

Глубину раздела надо ограничивать, но обрыв лежит НЕ там, где казалось. Замер
2026-08-27 по случайным выборкам оценивал смертность как «1-я — 15%, 3-я — 25%,
10-я — 75%» и обрывал ленту на третьей странице. Сплошная проверка того же
вечера — все 200 карточек первых десяти страниц, тем же `vacancy_alive`, что
стоит в прогоне, — показала другую кривую: 1-я 20%, 2-я 35%, 3-я 25%, 4-я 20%,
5-я 20%, 6-я 55%, 7-я 60%, 8-я 40%, 9-я 35%, 10-я 70%. Четвёртая и пятая
страницы живы РОВНО как первая, обрыв начинается с шестой — отсюда пять
(REMOCATE_PAGES), около 100 вакансий.

Дороже смертности здесь давно другое — цена оценки. Описание берётся из кэша
ленты, поэтому одна вакансия стоит только вызова модели (замер: 1,18 с против
~19 с на LinkedIn и ~38 с на hh, где за описание идёт отдельная страница), а
мёртвая ловится одним GET (2,7 с) ДО генерации. Тот же вечер, свежие карточки:
страницы 4-5 — 29 оценок на 2 живых подходящих лида, страницы 6-10 — 79 оценок
на 1. Пятая страница и есть точка, где лента перестаёт окупать сканирование.
Remocate — это не «две тысячи вакансий» (в разделе их 102 страницы по 20), а
быстрая узкая лента, которую надо опрашивать часто и неглубоко.

Мёртвых, которые всё-таки просочатся, ловит проверка перед отправкой
(infrastructure/vacancy_alive.py): она уже стоит на пути и стоит один запрос на
ЛИД, а не на каждую карточку ленты.

Описание вакансии лежит прямо в ленте (проверено: 4531 символ разметки в ленте
против 4519 на странице вакансии, текст тот же), поэтому describe() отвечает из
кэша, собранного во время search() — ни второго запроса, ни лишней задержки,
ровно как у RemoteOK и Remotive.
"""
import html as _html
import re
from urllib.parse import urljoin

import httpx

from app.domain.candidate import KIND_JOB, Candidate, normalize_url
from app.domain.keyword_match import title_matches

REMOCATE_BASE_URL = "https://www.remocate.app"
REMOCATE_FEED_URL = "https://www.remocate.app/job-categories/development"
# Вторая лента — буквально корень сайта, а не ещё один раздел, поэтому своей
# настройки адреса у неё нет: указывать её некуда. Настраивается только глубина
# (REMOCATE_HOME_PAGES), как и у раздела.
REMOCATE_HOME_URL = "https://www.remocate.app/"
DEFAULT_UA = "Mozilla/5.0 (compatible; telegram-jobs/1.0)"
# Пять страниц — граница живого запаса из замера выше, см. app/config.py.
DEFAULT_PAGES = 5
# Три страницы главной — точка, где она перестаёт приносить новое (4-я даёт +0
# карточек, которых не было в разделе) и всё ещё накрывает шесть дней публикаций.
DEFAULT_HOME_PAGES = 3

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# Сайт собран на Webflow, список вакансий — коллекция с фильтрами Finsweet.
# Разбор идёт по её АТРИБУТАМ (`fs-cmsfilter-field`), а не по классам оформления:
# классы меняет любая правка дизайна, а имена полей коллекции — это схема
# данных, и она переживает редизайн. По той же причине страница режется на
# элементы списка по `role="listitem"`, а не по классу `w-dyn-item` рядом с ним.
_ITEM_SPLIT_RE = re.compile(r'(?=<div role="listitem")')
# Первая ссылка на вакансию в куске — это ссылка САМОЙ карточки: она стоит
# сразу за открывающим `listitem`, раньше описания, в котором работодатель
# теоретически может сослаться на соседнюю вакансию.
_JOB_HREF_RE = re.compile(r'href="(/jobs/[^"]+)"')
_TITLE_RE = re.compile(r'fs-cmsfilter-field="name"[^>]*>(.*?)</div>', re.S)
_COMPANY_RE = re.compile(r'fs-cmsfilter-field="company"[^>]*>(.*?)</div>', re.S)
# У поля location на карточке ДВА значения: видимый тег страны («🌎 World»,
# «🇩🇪 Germany») и скрытый служебный «📍 Any Location» — он нужен фильтру, а не
# человеку. Различаются они только классом, поэтому здесь класс всё-таки нужен;
# спрашиваются оба признака заглядыванием вперёд, чтобы порядок атрибутов не
# решал ничего.
_LOCATION_RE = re.compile(
    r'<div\b(?=[^>]*fs-cmsfilter-field="location")(?=[^>]*class="job-card_tag")'
    r'[^>]*>(.*?)</div>', re.S)
_SALARY_RE = re.compile(r'fs-cmssort-field="salary"[^>]*>(.*?)</div>', re.S)
# Внутри описания вложенных <div> нет (проверено на живой ленте) — это готовый
# richtext из h2/p/ul/li, поэтому первый же </div> и есть закрывающий.
_DESC_RE = re.compile(r'class="job-card-desc[^"]*">(.*?)</div>', re.S)
# Листалка Webflow. Ссылку берём со страницы, а не собираем сами: имя параметра
# содержит хеш коллекции (`?c74bbb03_page=2`), который меняется при пересборке
# сайта. На последней странице (102/102) блок листалки есть, а «Next» в нём нет.
# Тег ищется отдельно от href, чтобы разбор пережил перестановку атрибутов.
_NEXT_ANCHOR_RE = re.compile(r'<a\b[^>]*\bclass="[^"]*\bw-pagination-next\b[^"]*"[^>]*>')
_HREF_RE = re.compile(r'href="([^"]*)"')


def strip_html(text: str) -> str:
    """Разметка -> текст. Сначала теги, потом сущности: иначе экранированный
    «&lt;p&gt;» превратился бы в тег уже после того, как теги сняты."""
    return _WS_RE.sub(" ", _html.unescape(_TAG_RE.sub(" ", text or ""))).strip()


def _field(pattern, chunk: str) -> str:
    m = pattern.search(chunk)
    return strip_html(m.group(1)) if m else ""


def parse_remocate_cards(html: str) -> list[dict]:
    """Карточки вакансий одной страницы ленты.

    Элементов списка на странице больше, чем вакансий: тем же `role="listitem"`
    свёрстан подвал со списком категорий (на живой странице 15 таких против 20
    настоящих). Карточкой считается только та, у которой есть ссылка на
    `/jobs/<slug>`; остальные молча пропускаются.
    """
    cards = []
    for chunk in _ITEM_SPLIT_RE.split(html or ""):
        href = _JOB_HREF_RE.search(chunk)
        if not href:
            continue
        cards.append({
            "url": urljoin(REMOCATE_BASE_URL, href.group(1)),
            "title": _field(_TITLE_RE, chunk),
            "company": _field(_COMPANY_RE, chunk),
            "location": _field(_LOCATION_RE, chunk),
            # Читается, но в лид не уезжает — см. to_candidate().
            "salary_estimate": _field(_SALARY_RE, chunk),
            "description": _field(_DESC_RE, chunk),
        })
    return cards


def to_candidate(job: dict) -> Candidate:
    """Карточка -> кандидат. Зарплата остаётся ПУСТОЙ, и это не пропуск.

    Число на карточке — оценка САМОГО САЙТА, а не работодателя. Замер 2026-08-27
    по 60 карточкам первых трёх страниц: значение лежит в
    `<div class="job-card-bubble hidden">`, то есть человеку сайт его не
    показывает; на странице вакансии зарплаты нет ни в каком виде; а значения
    кластеризуются строго по слову уровня в заголовке — одна и та же вилка
    «$115,000 – $195,500» стоит у ВСЕХ 16 карточек со словом Senior,
    «$80,500 – $138,000» — у 13 остальных.

    Если бы оно попало в Candidate.salary, `search_leads_repo._vacancy_text`
    написал бы строкой «Зарплата: …» в бриф, по которому генерируется письмо, и
    модель сослалась бы работодателю на вилку, которую тот никогда не
    публиковал. Локация — другое дело: её сайт показывает как есть.
    """
    return Candidate(
        platform="remocate", kind=KIND_JOB,
        url=job.get("url", ""),
        title=job.get("title", ""),
        company=job.get("company", ""),
        salary="",
        location=job.get("location", ""),
        summary="",
    )


def next_page_url(html: str, current_url: str) -> str:
    """Адрес следующей страницы ленты, или "" если её нет."""
    anchor = _NEXT_ANCHOR_RE.search(html or "")
    href = _HREF_RE.search(anchor.group(0)) if anchor else None
    return urljoin(current_url, _html.unescape(href.group(1))) if href else ""


class RemocateSearcher:
    name = "remocate"

    def __init__(self, feed_url: str = REMOCATE_FEED_URL,
                 pages: int = DEFAULT_PAGES,
                 home_url: str = REMOCATE_HOME_URL,
                 home_pages: int = DEFAULT_HOME_PAGES,
                 user_agent: str = DEFAULT_UA, timeout: int = 20):
        # Проходы в порядке УБЫВАНИЯ плотности: сначала раздел (79 прошедших
        # предфильтр на 100 карточек), потом главная (35 на 100, из них новых 8).
        # Порядок решает, кому достанется общий бюджет `limit`, если он мал.
        #
        # Ноль и минус в глубине значат «умолчание», а НЕ «без ограничения», в
        # отличие от соседних настроек (search_request.per_keyword_limit). Здесь
        # такое правило было бы вредным: в разделе 102 страницы, на главной 273,
        # а живого — первые пять и первые три; опечатка в .env превратила бы
        # поиск в обход кладбища на 5459 ссылок. Правило одно на обе глубины
        # намеренно: они стоят в .env соседними строками, и разное значение нуля
        # у них было бы ловушкой.
        self._passes: list[tuple[str, int]] = [
            (feed_url, pages if pages > 0 else DEFAULT_PAGES)]
        # Пустой адрес выключает второй проход. Настройки под это нет и быть не
        # должно: без главной бесхозные вакансии не видны вообще ничем.
        if home_url:
            self._passes.append(
                (home_url, home_pages if home_pages > 0 else DEFAULT_HOME_PAGES))
        self._ua = user_agent
        self._timeout = timeout
        self._desc: dict[str, str] = {}

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def _page(self, url: str) -> str:
        resp = httpx.get(url, headers={"User-Agent": self._ua},
                         timeout=self._timeout, follow_redirects=True)
        resp.raise_for_status()
        return resp.text

    def search(self, keywords_list, location, limit) -> list[Candidate]:
        # `location` принимается и не используется — как у RemoteOK и Remotive:
        # ленты у remocate общие на всех, страны в них перечислены тегом карточки
        # («🇩🇪 Germany»), а фильтра по стране в адресе нет.
        self._desc.clear()  # fresh per run — don't accumulate across worker loops
        found: list[Candidate] = []
        # `seen` — ОДИН на все проходы, потому что ленты пересекаются: главная
        # показывает и то, что лежит в разделах. Замер 2026-08-27: из 100
        # карточек первых пяти страниц главной 30 уже стояли в первых пяти
        # страницах development (на трёх страницах — 15 из 60). Каждая такая
        # вакансия без общего `seen` заняла бы второй слот в бюджете скоринга и
        # стоила бы второго вызова модели.
        seen: set[str] = set()
        for url, pages in self._passes:
            if not self._walk(url, pages, keywords_list, limit, found, seen):
                break
        return found

    def _walk(self, url: str, pages: int, keywords_list, limit,
              found: list[Candidate], seen: set[str]) -> bool:
        """Один проход по ленте. False = бюджет `limit` выбран, дальше не идём.

        Обрыв сети внутри прохода СЛЕДУЮЩИЙ проход не отменяет: это разные
        ленты, и 503-я на второй странице раздела — не повод не смотреть
        бесхозные вакансии, которых больше нигде нет.
        """
        for _ in range(pages):
            try:
                html = self._page(url)
            except Exception:  # noqa: BLE001 — contain our own network failures
                # Обрыв на третьей странице не обнуляет первые две. У соседей
                # вся выдача — один запрос, и там «упало = пусто» равнозначно;
                # здесь запросов несколько, и уже собранное дороже.
                return True
            for job in parse_remocate_cards(html):
                # Предфильтр по словам роли, как у RemoteOK и Remotive
                # (app.domain.keyword_match). Уровень он не смотрит: из 60
                # карточек живой ленты сюда проходят 49, и Senior / Lead /
                # Principal среди них хватает — их отсеивает скоринг
                # релевантности, тот же самый, что у остальных площадок.
                if not title_matches(job["title"], keywords_list):
                    continue
                key = normalize_url(job["url"])
                if not key or key in seen:
                    # Кроме пересечения лент между собой, тот же `seen` ловит
                    # сдвиг одной ленты под нами: страницы качаются подряд, и
                    # объявление, опубликованное между двумя запросами, гонит
                    # карточку с первой страницы на вторую. Дедуп листа от этого
                    # не спасает — он сравнивает с СОХРАНЁННЫМИ строками, а два
                    # одинаковых URL внутри одной выдачи для него оба новые.
                    continue
                seen.add(key)
                self._desc[key] = job["description"]
                found.append(to_candidate(job))
                if len(found) >= limit:
                    return False
            url = next_page_url(html, url)
            if not url:
                break
        return True

    def describe(self, url: str) -> str:
        return self._desc.get(normalize_url(url), "")
