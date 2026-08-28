"""HeadHunter searcher via a logged-in patchright browser.

hh.ru's applicant API is closed and its pages sit behind an anti-bot that
flags stock Playwright, so we drive real Chrome via patchright with the
session saved by `make login_hh` (shared with the outreach channel). hh.ru's
own query engine does the filtering — we do NOT re-filter titles by keyword
the way the API-fed boards do: relevant vacancies often have Russian titles. Raw DOM
extraction is isolated in _vacancy_cards / parse_hh_cards so selector drift
is easy to fix. start() refuses to run without a saved session instead of
prompting — the worker must never block on input().
"""
from urllib.parse import quote

from app.domain.candidate import KIND_JOB, Candidate, normalize_url
from app.domain.search_request import per_keyword_limit

HH_BASE_URL = "https://hh.ru"
# Страниц выдачи на один запрос. Страница отдаёт 50 карточек (замер живой
# выдачи 2026-08-27: [data-qa='vacancy-serp__vacancy'] -> ровно 50), а потолок
# на слово — SEARCH_PER_KEYWORD=25, поэтому вторая страница открывается только
# там, где фильтр оставил меньше 25 вакансий. На настройках по умолчанию таких
# слов ровно одно из 14: «next.js developer» — 23 удалённые вакансии за неделю.
# Значение по умолчанию, поверх него — HH_PAGES из .env.
SEARCH_PAGES = 2

# hh.ru data-qa hooks (verified live in Task 8; fix HERE when they drift).
SEL_CARD = "[data-qa='vacancy-serp__vacancy']"
SEL_TITLE = "[data-qa='serp-item__title']"
SEL_COMPANY = "[data-qa='vacancy-serp__vacancy-employer']"
SEL_SALARY = "[data-qa='vacancy-serp__compensation']"
SEL_ADDRESS = "[data-qa='vacancy-serp__vacancy-address']"
SEL_DESCRIPTION = "[data-qa='vacancy-description']"
_LOGIN_MARKERS = ("/account/login", "captcha")

# Значения фильтров, сняты с ЖИВОЙ панели «Фильтры» 2026-08-27 (имена полей
# формы: work_format, experience).
WORK_FORMATS = ("REMOTE", "HYBRID", "ON_SITE", "FIELD_WORK")
EXPERIENCE_LEVELS = ("noExperience", "between1And3", "between3And6", "moreThan6")


def _only_known(values, allowed):
    """Привести значение фильтра к тому виду, в котором hh его понимает.

    hh на неизвестное значение не ругается и НЕ отдаёт пусто — он молча
    выбрасывает фильтр и возвращает всё подряд. Замер 2026-08-27, «python
    developer», все четыре адреса подряд в один заход: work_format=REMOTE —
    1 712 вакансий, work_format=remote (тот же смысл, другой регистр) — 5 236,
    ровно столько же, сколько без фильтра вообще; так же отработали
    work_format=камни, experience=junior и area=999999. Значит опечатка в .env
    не ломает поиск с грохотом, она тихо
    возвращает его в состояние «до 2026-08-27» — с перекосом в московские
    офисы, ради которого фильтр и заводили.

    Отсюда регистр приводится здесь, а не оставляется на человека, а
    непонятные значения выбрасываются: в адрес они всё равно ничего не вносят,
    зато в нём видно, что реально применилось.
    """
    by_lower = {a.lower(): a for a in allowed}
    return [by_lower[str(v).strip().lower()]
            for v in values or () if str(v).strip().lower() in by_lower]


def valid_work_formats(values) -> list[str]:
    return _only_known(values, WORK_FORMATS)


def valid_experience(values) -> list[str]:
    return _only_known(values, EXPERIENCE_LEVELS)


def build_search_url(query: str, page: int = 0, areas=(), work_format=(),
                     experience=(), search_period: int = 0,
                     order_by: str = "") -> str:
    """Адрес выдачи hh со всеми фильтрами.

    Параметры сняты с ЖИВОЙ выдачи 2026-08-27: фильтры ставились руками в
    интерфейсе, адрес читался после применения.
      * кнопка «Показать N вакансий» в панели «Фильтры» ->
        /search/vacancy?text=python+developer&search_field=name&search_field=
        company_name&search_field=description&work_format=REMOTE&...
      * чип «Регион» -> /search/vacancy?text=python+developer&area=40&...
      * меню сортировки, пункт «По дате» -> ...&order_by=publication_time
      * меню периода: search_period=1|3|7|30 (подпись меняется на «За день»,
        «За три дня», «За неделю», «За месяц»).

    Одноимённые параметры hh складывает по ИЛИ, и только повторением: замер
    «python developer» — work_format=REMOTE 1 708 вакансий, два параметра
    REMOTE и HYBRID 2 764, а одно значение «REMOTE,HYBRID» — 5 236, ровно
    столько же, сколько вообще без фильтра. Запятую hh не понимает и молча
    снимает фильтр, поэтому список разворачивается в повторяющиеся пары.

    search_field (искать в названии / в компании / в описании) в адрес не
    кладём: живая выдача пишет туда все три значения, то есть это и есть
    умолчание hh, а сузить область поиска здесь значит потерять вакансию, где
    нужное слово стоит только в описании.

    Пустой набор = фильтра нет вовсе. Прежний голый адрес (только text и page)
    получается сам собой, если ничего не настроено, — обновление не ломает уже
    работающие прогоны.
    """
    parts = [f"text={quote(query)}", f"page={page}"]
    for area in areas or ():
        parts.append(f"area={quote(str(area))}")
    for fmt in work_format or ():
        parts.append(f"work_format={quote(str(fmt))}")
    for level in experience or ():
        parts.append(f"experience={quote(str(level))}")
    if search_period:
        # Ноль — «за всё время», а не «за ноль дней». Замер 2026-08-27:
        # search_period=30 и отсутствие параметра дают одно и то же число
        # (5 236 по «python developer»), то есть глубже месяца hh и так не
        # хранит; сужают только 7 (1 913) и 1 (467).
        parts.append(f"search_period={int(search_period)}")
    if order_by:
        parts.append(f"order_by={quote(order_by)}")
    return f"{HH_BASE_URL}/search/vacancy?" + "&".join(parts)


def parse_hh_cards(cards, limit: int) -> list[Candidate]:
    out = []
    for card in cards:
        title = card.get_text("title")
        url = card.get_href()
        if not title or not url:
            continue
        out.append(Candidate(
            platform="hh", kind=KIND_JOB, url=url,
            title=title, company=card.get_text("company"),
            salary=card.get_text("salary"), location=card.get_text("location"),
            summary="",
        ))
        if len(out) >= limit:
            break
    return out


class _LiveCard:
    """Adapts a Playwright element's already-read text into the parser interface."""

    def __init__(self, title, company, salary, location, href):
        self._d = {"title": title, "company": company,
                   "salary": salary, "location": location}
        self._href = href or ""

    def get_text(self, role):
        return (self._d[role] or "").strip()

    def get_href(self):
        return self._href


def _http_vacancy_text(url: str) -> str:
    """Описание вакансии по HTTP, "" если не прочиталось. Импорт ленивый: чтение
    страниц живёт в другом слое, и тянуть его при разборе модуля незачем."""
    from app.infrastructure.vacancy_fetcher import fetch_vacancy_text
    try:
        return fetch_vacancy_text(url)
    except Exception:  # noqa: BLE001 — сеть отвалилась: остаётся браузер
        return ""


class HHSearcher:
    name = "hh"

    def __init__(self, storage_state_path: str, headless: bool = False,
                 per_keyword: int = 25, areas=None, work_format=None,
                 experience=None, search_period: int = 0, order_by: str = "",
                 pages: int = SEARCH_PAGES, fetch_text=None):
        self._fetch_text = fetch_text or _http_vacancy_text
        self._storage_state_path = storage_state_path
        self._headless = headless
        self._per_keyword = per_keyword
        self._areas = [str(a).strip() for a in (areas or []) if str(a).strip()]
        self._work_format = valid_work_formats(work_format)
        self._experience = valid_experience(experience)
        self._search_period = search_period
        self._order_by = order_by
        self._pages = max(1, pages)
        self._pw = None
        self._browser = None
        self._page = None

    def start(self) -> None:
        from pathlib import Path

        if not Path(self._storage_state_path).exists():
            raise RuntimeError(
                f"Сессия hh.ru не найдена ({self._storage_state_path}). "
                "Сначала выполни `make login_hh`")

        from patchright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._headless, channel="chrome")
        context = self._browser.new_context(
            storage_state=self._storage_state_path, no_viewport=True)
        self._page = context.new_page()

    def stop(self) -> None:
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    @staticmethod
    def _text(el, selector):
        """First match's text, or '' — fast-fail so drift doesn't hang per card."""
        try:
            return el.locator(selector).first.inner_text(timeout=2000)
        except Exception:  # noqa: BLE001
            return ""

    def _vacancy_cards(self):
        cards = []
        for el in self._page.locator(SEL_CARD).all():
            try:
                href = el.locator(SEL_TITLE).first.get_attribute("href", timeout=2000)
            except Exception:  # noqa: BLE001
                href = ""
            cards.append(_LiveCard(
                title=self._text(el, SEL_TITLE),
                company=self._text(el, SEL_COMPANY),
                salary=self._text(el, SEL_SALARY),
                location=self._text(el, SEL_ADDRESS),
                href=href,
            ))
        return cards

    def _url(self, query: str, page_n: int) -> str:
        return build_search_url(
            query, page_n, areas=self._areas, work_format=self._work_format,
            experience=self._experience, search_period=self._search_period,
            order_by=self._order_by)

    def search(self, keywords_list, location, limit) -> list[Candidate]:
        """`location` намеренно не используется: у hh своя география.

        Через run_search сюда приходит общая для всех площадок строка
        SEARCH_LOCATION («Worldwide») — понятие LinkedIn. hh адресует регионы
        числовыми id (40 = Казахстан, 113 = Россия, 159 = Астана), подставить
        туда строку нельзя, поэтому регион у hh задаётся своим списком
        HH_AREAS. Аргумент остаётся в подписи: она общая для всех searcher'ов.
        """
        found: list[Candidate] = []
        seen: set[str] = set()
        per_kw = per_keyword_limit(limit, len(keywords_list), self._per_keyword)
        for query in keywords_list:
            kw_found = 0
            for page_n in range(self._pages):
                if kw_found >= per_kw:
                    break
                try:
                    self._page.goto(self._url(query, page_n),
                                    wait_until="domcontentloaded", timeout=30000)
                except Exception:  # noqa: BLE001 — one page failing must not kill the rest
                    break
                if any(m in self._page.url for m in _LOGIN_MARKERS):
                    # Expired/invalid session: fail loudly instead of silently
                    # returning 0 candidates (run_search reports it per-platform).
                    raise RuntimeError(
                        "Сессия hh.ru истекла или требуется вход — выполни `make login_hh`")
                try:
                    self._page.wait_for_selector(SEL_CARD, timeout=12000)
                except Exception:  # noqa: BLE001
                    break
                for c in parse_hh_cards(self._vacancy_cards(), limit):
                    key = normalize_url(c.url)
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    found.append(c)
                    kw_found += 1
                    if len(found) >= limit:
                        return found
                    if kw_found >= per_kw:
                        break
        return found

    def describe(self, url: str) -> str:
        """Текст вакансии для скоринга — простым HTTP, браузером только запасным ходом.

        Описание hh лежит в серверной разметке и открывается БЕЗ логина: замер
        2026-08-28, 14 случайных вакансий подряд без пауз — 14 ответов 200,
        0,60 с на страницу, описание нашлось в 13 (четырнадцатая в архиве, там
        блока нет и у браузера). Через браузер та же страница обходится ~38 с:
        грузятся скрипты, стили и картинки, а нужен один блок текста.

        Ценой этих 38 с и живёт потолок MATCH_SCAN_LIMIT: 150 оценок = полтора
        часа на площадку. Дешёвое чтение снимает не сам потолок, а причину, по
        которой он стоит так низко.

        Запасной ход оставлен на случай переезда разметки: без него дрейф
        одного `data-qa` обнулил бы скоринг всей площадки. Молчаливым он не
        будет — время площадки печатается в отчёте прогона, и возврат к часам
        виден там сразу.
        """
        text = self._fetch_text(url)
        if text:
            return text[:6000]
        try:
            self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
            text = self._page.locator(SEL_DESCRIPTION).first.inner_text(timeout=15000)
            return text.strip()[:6000]
        except Exception:  # noqa: BLE001
            return ""
