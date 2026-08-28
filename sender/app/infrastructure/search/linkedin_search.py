"""LinkedIn vacancy/recruiter search via a logged-in Playwright session.

Automating LinkedIn violates its ToS and risks an account ban (accepted by the
user). Raw DOM extraction is isolated in parse_* (selectors drift); the class
collects "card" wrappers and hands them to the pure parsers.
"""
from urllib.parse import urlencode

from app.domain.candidate import Candidate, KIND_JOB, KIND_PROFILE
from app.infrastructure.search.describe_http import http_vacancy_text


# Сколько вакансий LinkedIn отдаёт на одной странице выдачи (замер живой
# страницы 2026-08-03: li[data-occludable-job-id] -> ровно 25). Следующая
# страница адресуется смещением start=25, 50, ...
PAGE_SIZE = 25

# Сколько снимков списка делать, прокручивая страницу. Пять шагов на 25 карточек
# с запасом: замер показал, что одновременно отрисовано около десяти.
_SCROLL_STEPS = 5
_SCROLL_SETTLE_MS = 900

# Снимок всего списка одним вызовом. Заголовок дублируется скрытым span-ом для
# скринридеров, поэтому берётся только первая строка.
_HARVEST_JS = """() => {
  const out = [];
  document.querySelectorAll('li[data-occludable-job-id]').forEach(li => {
    const pick = sel => {
      const el = li.querySelector(sel);
      return el ? (el.innerText || '').split('\\n')[0].trim() : '';
    };
    out.push({
      id: li.getAttribute('data-occludable-job-id') || '',
      title: pick('.artdeco-entity-lockup__title'),
      company: pick('.artdeco-entity-lockup__subtitle'),
      location: pick('.artdeco-entity-lockup__caption'),
    });
  });
  return out;
}"""

# Прокрутка к элементу с нужным порядковым номером: скроллим сам список, а не
# окно — выдача LinkedIn живёт в своей прокручиваемой колонке.
_SCROLL_JS = """(step) => {
  const items = document.querySelectorAll('li[data-occludable-job-id]');
  if (!items.length) return;
  const idx = Math.min(items.length - 1, Math.ceil(items.length * step / 5));
  items[idx].scrollIntoView({block: 'center'});
}"""


def build_jobs_url(keywords: str, location: str,
                   experience: str = "1,2,3", posted_within: str = "r604800",
                   workplace: str = "", start: int = 0) -> str:
    """Ссылка на выдачу LinkedIn.

    `workplace` (f_WT: 1=офис, 2=удалённо, 3=гибрид) по умолчанию ПУСТОЙ — то
    есть подходит любой формат. Раньше здесь стояло f_WT=2 константой, которую
    нельзя было выключить, и она отсекала 60–75% вакансий: замер 2026-08-03 за
    неделю дал «python developer» 1000+ удалённых против 3000+ всего, а
    «ai engineer» — 2000+ против 8000+. Человеку, готовому к релокации, этот
    фильтр отрезал именно то, что ему подходит.
    """
    qs = {
        "keywords": keywords,
        "location": location,
        "f_TPR": posted_within,  # recency window (r604800 = 7 days)
    }
    if workplace:
        qs["f_WT"] = workplace
    if experience:
        qs["f_E"] = experience   # 1=Internship, 2=Entry/Junior, 3=Associate/Junior+
    if start:
        qs["start"] = start
    return f"https://www.linkedin.com/jobs/search/?{urlencode(qs)}"


def build_people_url(keywords: str) -> str:
    qs = urlencode({"keywords": keywords})
    return f"https://www.linkedin.com/search/results/people/?{qs}"


def _rotate(items: list, by: int) -> list:
    """Тот же список, начиная с элемента `by` (по кругу)."""
    if not items:
        return items
    k = by % len(items)
    return items[k:] + items[:k]


def merge_harvest(batches) -> list:
    """Собрать карточки из нескольких «снимков» списка в один набор без дублей.

    Список выдачи виртуализирован: LinkedIn держит отрисованными только видимые
    карточки и перерабатывает их при скролле. Замер 2026-08-03: в списке 25
    элементов li[data-occludable-job-id], а отрисованных div.job-card-container
    всего 7, и после прокрутки стало 10, а не 25. Значит увидеть все сразу
    нельзя — снимки делаются по ходу скролла и склеиваются здесь.

    Идентификатор вакансии есть у каждого li сразу, поэтому ссылка собирается
    даже для карточки, которая так и не отрисовалась: заголовок это бонус
    (описание всё равно читает describe() со страницы вакансии), а потерянная
    ссылка — потерянная вакансия.
    """
    by_id: dict[str, dict] = {}
    for batch in batches:
        for row in batch or []:
            jid = str((row or {}).get("id") or "").strip()
            if not jid:
                continue
            seen = by_id.setdefault(jid, {"title": "", "company": "", "location": ""})
            for field in ("title", "company", "location"):
                value = str(row.get(field) or "").strip()
                if value and not seen[field]:
                    seen[field] = value
    return [
        _LiveCard(title=v["title"], company=v["company"], location=v["location"],
                  href=f"https://www.linkedin.com/jobs/view/{jid}/")
        for jid, v in by_id.items()
    ]


def parse_job_cards(cards, limit: int) -> list[Candidate]:
    out = []
    for card in cards[:limit]:
        out.append(Candidate(
            platform="linkedin", kind=KIND_JOB,
            url=card.get_href(),
            title=card.get_text("title"),
            company=card.get_text("company"),
            salary="",  # LinkedIn rarely exposes salary
            location=card.get_text("location"),
            summary="",
        ))
    return out


def parse_people_cards(cards, limit: int) -> list[Candidate]:
    out = []
    for card in cards[:limit]:
        out.append(Candidate(
            platform="linkedin", kind=KIND_PROFILE,
            url=card.get_href(),
            title=card.get_text("title"),
            company=card.get_text("company"),  # headline goes here
            salary="",
            location=card.get_text("location"),
            summary="",
        ))
    return out


class LinkedInSearcher:
    name = "linkedin"

    def __init__(self, storage_state_path: str, headless: bool = True,
                 people_enabled: bool = False,
                 experience: str = "1,2,3", posted_within: str = "r604800",
                 workplace: str = "", per_keyword: int = PAGE_SIZE,
                 pages: int = 1, locations=None, rotate_by: int = 0):
        self._storage_state_path = storage_state_path
        self._headless = headless
        self._people_enabled = people_enabled
        self._experience = experience
        self._posted_within = posted_within
        self._workplace = workplace
        self._per_keyword = per_keyword
        self._pages = max(1, pages)
        self._locations = list(locations) if locations else []
        self._rotate_by = rotate_by
        self._pw = None
        self._browser = None
        self._page = None

    def start(self) -> None:
        from playwright.sync_api import sync_playwright

        from app.infrastructure.linkedin_session import has_valid_session

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._headless)
        # A file that exists but carries no live `li_at` is a logged-out session:
        # loading it browses as a guest and every page dead-ends at the authwall.
        # Treat it as "no session" so `make login_browser` opens the login window
        # instead of silently keeping the dead cookies.
        state = self._storage_state_path if has_valid_session(self._storage_state_path) else None
        context = self._browser.new_context(storage_state=state)
        self._page = context.new_page()
        if state is None:
            self._page.goto("https://www.linkedin.com/login")
            input("Залогинься в LinkedIn в открытом окне, потом нажми Enter здесь...")
            context.storage_state(path=self._storage_state_path)

    def stop(self) -> None:
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    @staticmethod
    def _text(el, selector):
        """First match's text, or '' — fast-fail so drift doesn't hang 30s/card."""
        try:
            return el.locator(selector).first.inner_text(timeout=2000)
        except Exception:  # noqa: BLE001
            return ""

    def _job_cards(self):
        """Все вакансии страницы выдачи, а не только отрисованные.

        Список виртуализирован (см. merge_harvest): прежний обход
        `div.job-card-container` видел 7 карточек из 25. Поэтому страница
        прокручивается шагами, после каждого делается снимок всего списка, и
        снимки склеиваются.

        Один evaluate на снимок вместо локаторов на каждое поле: 25 карточек по
        три поля — это 75 обращений с таймаутами, из которых каждое непопадание
        стоит секунды.
        """
        batches = []
        for step in range(_SCROLL_STEPS):
            try:
                batches.append(self._page.evaluate(_HARVEST_JS))
            except Exception:  # noqa: BLE001 — снимок это не повод ронять прогон
                break
            if step == _SCROLL_STEPS - 1:
                break
            try:
                self._page.evaluate(_SCROLL_JS, step + 1)
                self._page.wait_for_timeout(_SCROLL_SETTLE_MS)
            except Exception:  # noqa: BLE001
                break
        return merge_harvest(batches)

    def describe(self, url: str) -> str:
        """Текст вакансии для скоринга — простым HTTP, браузером только запасным ходом.

        То же, что на hh, и по той же причине (см. HHSearcher.describe), плюс
        одна своя: здесь браузер ходит ПОД ЛОГИНОМ. Полторы сотни заходов на
        страницы вакансий за прогон — ровно тот след, за который в августе
        прилетел бан. Простой HTTP идёт анонимно, аккаунта не касается вовсе.

        Замер 2026-08-28: шесть случайных вакансий из памяти скорера — 6 из 6,
        0,78-1,05 с, описание полное, с названием компании. Через браузер та же
        страница обходилась ~19 с.

        Профили людей (`/in/…`) читалка не знает и отдаёт пусто — они уходят на
        запасной ход, как и раньше.
        """
        text = http_vacancy_text(url)
        if text:
            return text[:6000]
        self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
        self._page.wait_for_timeout(2000)
        for sel in ["#job-details", ".jobs-description__content",
                    ".jobs-box__html-content", ".description__text", "article", "main"]:
            try:
                text = self._page.locator(sel).first.inner_text(timeout=2500)
                if text.strip():
                    return text.strip()[:6000]
            except Exception:  # noqa: BLE001
                continue
        return ""

    def _people_cards(self):
        cards = []
        for el in self._page.locator("li.reusable-search__result-container").all():
            cards.append(_LiveCard(
                title=el.locator("span.entity-result__title-text a").first.inner_text(),
                company=el.locator(".entity-result__primary-subtitle").inner_text(),
                location="",
                href=el.locator("span.entity-result__title-text a").first.get_attribute("href"),
            ))
        return cards

    def search(self, keywords_list, location, limit) -> list[Candidate]:
        """Перебор ключевое слово × локация × страница, пока не наберём `limit`.

        Локаций может быть несколько: раньше на всё была одна строка
        SEARCH_LOCATION, и вакансии в UAE, Турции или отдельных странах EU не
        искались никогда.
        """
        from app.domain.search_request import per_keyword_limit
        per_kw = per_keyword_limit(limit, len(keywords_list), self._per_keyword)
        locations = self._locations or [location]
        found: list[Candidate] = []
        # Страница — ВНЕШНИЙ цикл, ключевое слово — внутренний. Порядок не
        # косметика: бюджет платформы обрывает обход, и при обходе «слово, потом
        # его страницы» первое же слово выбирало бы весь лимит, а до QA и AI
        # очередь не доходила бы никогда. Именно от этого защищала прежняя
        # делёжка бюджета — теперь то же самое делает порядок.
        # Бюджет обрывает обход, поэтому стартовая пара сдвигается от прогона к
        # прогону: иначе опрашивались бы вечно одни и те же первые запросы, а
        # остальные роли и страны не искались бы никогда.
        keywords_list = _rotate(list(keywords_list), self._rotate_by)
        locations = _rotate(list(locations), self._rotate_by)
        exhausted: set[tuple[str, str]] = set()
        for page in range(self._pages):
            for loc in locations:
                for kw in keywords_list:
                    if (kw, loc) in exhausted:
                        continue        # по этой паре вакансии кончились
                    self._page.goto(
                        build_jobs_url(kw, loc, self._experience,
                                       self._posted_within, self._workplace,
                                       start=page * PAGE_SIZE),
                        wait_until="domcontentloaded")
                    cards = self._job_cards()
                    found += parse_job_cards(cards, limit=per_kw)
                    if not cards:
                        exhausted.add((kw, loc))
                    if len(found) >= limit:
                        return found[:limit]
        if self._people_enabled:
            for kw in keywords_list:
                self._page.goto(build_people_url(kw), wait_until="domcontentloaded")
                found += parse_people_cards(self._people_cards(), limit=per_kw)
                if len(found) >= limit:
                    return found[:limit]
        return found[:limit]


class _LiveCard:
    """Adapts a Playwright element's already-read text into the parser interface."""

    def __init__(self, title, company, location, href):
        self._d = {"title": title, "company": company, "location": location}
        self._href = href if str(href).startswith("http") else f"https://www.linkedin.com{href}"

    def get_text(self, role):
        return (self._d[role] or "").strip()

    def get_href(self):
        return self._href
