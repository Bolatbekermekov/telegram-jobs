"""Wellfound vacancy search via a logged-in Playwright session.

Automating Wellfound violates its ToS and risks a ban (accepted by the user).
DOM extraction isolated in parse_job_cards (selectors drift).
"""
from urllib.parse import urlencode

from app.domain.candidate import Candidate, KIND_JOB

# Поля страницы, которые решают, ПРИМЕТ ли Wellfound заявку. Лежат отдельно от
# описания вакансии, поэтому `describe()` их раньше терял: замер живой страницы
# 2026-08-02 показал, что элемент с классом `description` (3224 символа) не
# содержит ни «Hires remotely in», ни «Visa Sponsorship». Скорер видел только
# «Remote only», ставил 82/100 и не знал про список из девяти разрешённых стран
# — несовпадение вскрывалось лишь на отклике, после вызова скорера, генерации
# письма и поднятого браузера. Так ушли в мусор 3 из 5 лидов Wellfound.
_ELIGIBILITY_FIELDS = (
    "Hires remotely in",
    "Remote Work Policy",
    "Preferred Timezones",
    "Visa Sponsorship",
    "Relocation",
    "Company Location",
)

# Где заканчивается значение поля: следующее известное поле или соседняя секция.
_ELIGIBILITY_STOP = _ELIGIBILITY_FIELDS + ("Skills", "Reposted", "Posted", "Apply")


# Что видно в окне входа, пока человек его проходит. Три состояния, и различать
# их надо, потому что ждём мы по-разному: Cloudflare сам уходит через несколько
# секунд, а форма входа — только когда человек введёт пароль.
_CLOUDFLARE_MARKERS = ("момент", "moment", "just a", "checking your browser",
                       "attention required")


def login_state(url: str, title: str) -> str:
    """«cloudflare» | «login» | «ready» — по адресу и заголовку вкладки.

    Нужна отдельной функцией, потому что вход в Wellfound нельзя дождаться через
    `input()`: команду запускают из оболочки без stdin, и `input()` там падает с
    EOFError, не дав человеку залогиниться вовсе (живьём 2026-08-29, ровно как
    раньше с `make login_browser`). Значит ждать надо опросом, а решение об
    ожидании — чистое и проверяемое.
    """
    t = (title or "").strip().lower()
    u = (url or "").strip().lower()
    if any(m in t for m in _CLOUDFLARE_MARKERS):
        return "cloudflare"
    if "/login" in u or "/signin" in u or "/join" in u:
        return "login"
    if not u or not u.startswith("http"):
        return "cloudflare"          # about:blank — вкладка ещё не доехала
    return "ready"


def eligibility_block(page_text: str) -> str:
    """Условия найма со страницы вакансии, одной короткой выжимкой.

    Идёт в промпт скорера рядом с описанием, поэтому здесь только то, что
    влияет на допуск: страны, визу, релокацию, формат и таймзону. Секция Skills
    и служебные строки отбрасываются — в промпте они стоят денег и ничего не
    решают.
    """
    lines = [s.strip() for s in (page_text or "").splitlines() if s.strip()]
    out = []
    for i, line in enumerate(lines):
        if line not in _ELIGIBILITY_FIELDS:
            continue
        values = []
        for nxt in lines[i + 1:]:
            if nxt in _ELIGIBILITY_STOP:
                break
            values.append(nxt.rstrip(" -"))
        if values:
            out.append(f"{line}: {', '.join(values)}")
    return "\n".join(out)


# Слаг роли у Wellfound СВОЙ, из нашего слова он не выводится. Проверено живьём
# 2026-08-29 по всем четырнадцати словам: восемь слагов совпали механически
# (`golang-developer`, `backend-developer`, `python-developer`, `react-developer`,
# `ai-engineer`, `full-stack-developer`, `qa-engineer`, `qa-automation-engineer`),
# а шесть страниц не существует вовсе — `nodejs-developer`, `nextjs-developer`,
# `vue-developer`, `react-native-developer`, `mobile-developer`, `llm-engineer`
# отдают ноль вакансий. Поэтому здесь таблица, а не только механика.
# Найденные замены (замер того же дня, число — счётчик самой площадки):
#   node.js developer      -> node-js-developer            12
#   next.js developer      -> javascript-developer        523   (замена по смыслу:
#       страниц next-js-developer, nextjs-engineer и даже frontend-developer у
#       Wellfound нет вовсе — последнее неожиданно, но проверено)
#   vue developer          -> vue-js-developer               5
#   react native developer -> mobile-engineer              847
#   mobile developer       -> mobile-engineer              847   (тот же слаг!)
#   llm engineer           -> machine-learning-engineer    833
# Два слова, ведущие на одну страницу, — не ошибка таблицы, а свойство
# справочника Wellfound. Второй запрос за ней не идёт: слаги в search()
# опрашиваются по одному разу.
_ROLE_SLUGS: dict[str, str] = {
    "node.js developer": "node-js-developer",
    "next.js developer": "javascript-developer",
    "vue developer": "vue-js-developer",
    "react native developer": "mobile-engineer",
    "mobile developer": "mobile-engineer",
    "llm engineer": "machine-learning-engineer",
}


def role_slug(keyword: str) -> str:
    """Слаг страницы роли Wellfound для нашего ключевого слова."""
    kw = (keyword or "").strip().lower()
    if kw in _ROLE_SLUGS:
        return _ROLE_SLUGS[kw]
    out, prev_dash = [], True
    for ch in kw.replace(".", ""):
        if ch.isalnum():
            out.append(ch)
            prev_dash = False
        elif not prev_dash:
            out.append("-")
            prev_dash = True
    return "".join(out).strip("-")


def build_jobs_url(keyword: str, remote_only: bool = False, page: int = 1) -> str:
    """Адрес выдачи Wellfound. СТРАНИЦА РОЛИ, а не `/jobs?q=`.

    `/jobs` не слышит ни одного параметра запроса. Замер 2026-08-29: `?q=`,
    `?keywords=`, `job_search[keywords]` и `&page=2` дают ПОБАЙТНО один и тот же
    набор — 17 вакансий и счётчик «192 results», — и он же выдаётся на голый
    `/jobs`. Это не наша выдача, а СОХРАНЁННЫЙ ПОИСК владельца («Software
    Engineer | Europe | Full Time»), который площадка показывает вошедшему.
    Отсюда и вечный ноль: все четырнадцать слов ходили за одной и той же
    страницей, её 17 вакансий скорер отверг ещё в июле и запомнил.

    Три РАЗНЫХ слова («qa engineer», «golang developer», «react native
    developer») дали пересечение 17 из 17 — то есть выдача не сужалась, она
    просто не менялась.

    Страница роли слышит и слово, и номер страницы. Те же 14 слов через неё:
    ai engineer — 4757 вакансий, backend developer — 955, python — 836,
    full stack — 721, react — 697, qa engineer — 509, qa automation — 229,
    golang — 56; на первых страницах восьми рабочих слагов 245 РАЗНЫХ вакансий
    против сегодняшних 17. Вторая страница `golang-developer` дала 22 карточки,
    из них новых против первой — все 22.

    `/role/r/<slug>` — та же роль, но уже, и это подмножество: 26 против 56 у
    `/role/<slug>`, пересечение 17. Отсюда `remote_only` и адресуется им.
    """
    slug = role_slug(keyword)
    base = f"https://wellfound.com/role/{'r/' if remote_only else ''}{slug}"
    return f"{base}?{urlencode({'page': page})}" if page and page > 1 else base


def parse_job_cards(cards, limit: int) -> list[Candidate]:
    out = []
    for card in cards[:limit]:
        out.append(Candidate(
            platform="wellfound", kind=KIND_JOB,
            url=card.get_href(),
            title=card.get_text("title"),
            company=card.get_text("company"),
            salary=card.get_text("salary"),
            location=card.get_text("location"),
            summary="",
        ))
    return out


def build_chrome_debug_args(profile_dir: str, port: int, url: str) -> list[str]:
    """CLI args for launching the user's real Chrome with a remote-debug port.

    --no-first-run / --no-default-browser-check stop a fresh profile from
    hijacking the launch with chrome://intro so `url` actually opens.
    """
    return [
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        url,
    ]


class WellfoundSearcher:
    name = "wellfound"

    def __init__(self, storage_state_path: str, headless: bool = True,
                 cdp_url: str | None = None, per_keyword: int = 25,
                 remote_only: bool = False, pages: int = 2):
        self._storage_state_path = storage_state_path
        self._headless = headless
        self._cdp_url = cdp_url
        self._per_keyword = per_keyword
        self._remote_only = remote_only
        self._pages = max(1, pages)
        self._pw = None
        self._browser = None
        self._page = None

    @property
    def uses_cdp(self) -> bool:
        return self._cdp_url is not None

    def start(self) -> None:
        from pathlib import Path

        from patchright.sync_api import sync_playwright

        self._pw = sync_playwright().start()

        # Primary path: attach to the user's already-open, human-driven Chrome
        # (where Cloudflare Turnstile is already passed). A separately launched
        # browser — stock Playwright OR patchright — just loops on the challenge,
        # because cf_clearance is bound to the browser that solved it. Reuse the
        # warm tab; do NOT navigate/re-create context here.
        if self._cdp_url:
            self._browser = self._pw.chromium.connect_over_cdp(self._cdp_url)
            context = self._browser.contexts[0]
            self._page = context.pages[0] if context.pages else context.new_page()
            return

        # Fallback launch path (kept for completeness; will hit the challenge).
        self._browser = self._pw.chromium.launch(headless=self._headless, channel="chrome")
        state = self._storage_state_path if Path(self._storage_state_path).exists() else None
        context = self._browser.new_context(storage_state=state, no_viewport=True)
        self._page = context.new_page()
        if state is None:
            self._page.goto("https://wellfound.com/login")
            input("Залогинься в Wellfound в открытом окне, потом нажми Enter здесь...")
            context.storage_state(path=self._storage_state_path)

    def stop(self) -> None:
        # In CDP mode leave the user's Chrome running; only drop our connection.
        if self._browser and not self._cdp_url:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    # Карточки снимаются ОДНИМ вызовом в странице, а не локаторами по одной:
    # сорок пять ссылок × несколько обращений каждая — это сотни round-trip'ов
    # по CDP (тот же урок, что на карточках hh).
    #
    # Опора — ссылка на вакансию и ближайший h2 сверху, а не разметка контейнера.
    # Причина замерена 2026-08-29: на `/role/<slug>` элементов
    # `[data-test='StartupResult']` РОВНО НОЛЬ — их вообще нет на странице, там
    # только tailwind-классы вида `mb-6 w-full rounded border border-gray-400`.
    # Прежний сбор ждал этот контейнер по 15 секунд и возвращал пусто, отчего
    # прогон длился 3 м 34 с и находил ноль при 45 ссылках на странице.
    # Классы верстки в опору не годятся — они меняются с каждой пересборкой;
    # ссылка `/jobs/<цифры>-…` и заголовок компании держатся.
    _CARDS_JS = """() => {
      const out = [];
      for (const a of document.querySelectorAll("a[href*='/jobs/']")) {
        const href = a.getAttribute('href') || '';
        const slug = href.split('/jobs/')[1] || '';
        if (!/^\\d/.test(slug)) continue;          // /jobs/home и прочая навигация
        const title = (a.textContent || '').trim().split('\\n')[0].trim();
        if (!title) continue;
        let company = '';
        let node = a;
        for (let i = 0; i < 8 && node; i++) {
          const h = node.querySelector && node.querySelector('h2');
          if (h && (h.textContent || '').trim()) {
            company = h.textContent.trim().split('\\n')[0].trim();
            break;
          }
          node = node.parentElement;
        }
        out.push({ title, company, href });
      }
      return out;
    }"""

    def _job_cards(self):
        """Одна карточка на роль, компания — из ближайшего h2 над ссылкой.

        Зарплата и локация приходят слипшимся комом на роль, поэтому остаются
        пустыми: надёжны название, компания и адрес.
        """
        try:
            self._page.wait_for_selector("a[href*='/jobs/']", timeout=15000)
        except Exception:  # noqa: BLE001 — роли с таким слагом у площадки нет
            return []
        try:
            raw = self._page.evaluate(self._CARDS_JS)
        except Exception:  # noqa: BLE001
            return []
        return [
            _LiveCard(title=r["title"], company=r["company"], salary="", location="",
                      href=(r["href"] if r["href"].startswith("http")
                            else f"https://wellfound.com{r['href']}"))
            for r in raw
        ]

    def job_cards_for_test(self):
        """Тот же сбор, что в прогоне. Отдельное имя — чтобы тест не лез в _job_cards."""
        return self._job_cards()

    def describe(self, url: str) -> str:
        """Open a job page and return its description text (best-effort).

        Wellfound renders the description (React) into an element whose class
        contains 'description'; wait for it, then take the first sizeable block
        (skip the small company-header section).
        """
        self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
        try:
            self._page.wait_for_selector("[class*='description']", timeout=12000)
        except Exception:  # noqa: BLE001
            self._page.wait_for_timeout(4000)
        # Условия найма берутся со ВСЕЙ страницы, а не из блока описания: они
        # лежат вне него (проверено живьём 2026-08-02). Без них скорер не видит
        # список стран и пропускает вакансии, заявку на которые площадка всё
        # равно не примет.
        try:
            eligibility = eligibility_block(self._page.inner_text("body", timeout=2500))
        except Exception:  # noqa: BLE001 — условия это бонус, не повод падать
            eligibility = ""

        for sel in ["[class*='description']", "[data-test='JobDescription']",
                    "div.styles_description__"]:
            try:
                text = self._page.locator(sel).first.inner_text(timeout=2500)
                if len(text.strip()) > 100:
                    body = text.strip()[:6000]
                    return f"{body}\n\n=== УСЛОВИЯ НАЙМА ===\n{eligibility}" if eligibility else body
            except Exception:  # noqa: BLE001
                continue
        return eligibility

    def search(self, keywords_list, location, limit) -> list[Candidate]:
        """Обход «страница снаружи, слово внутри» — как у LinkedIn и по той же
        причине: бюджет обрывает перебор, и при обратном порядке первое слово
        выбирало бы его целиком, а до QA и мобилок очередь не доходила бы.

        Слово, не давшее НИ ОДНОЙ карточки, дальше не опрашивается: у Wellfound
        свой справочник ролей, страницы для шести наших слов в нём нет вовсе
        (см. role_slug), а пустая страница стоит пятнадцати секунд ожидания
        `StartupResult` — на каждом следующем проходе заново.
        """
        from app.domain.search_request import per_keyword_limit
        per_kw = per_keyword_limit(limit, len(keywords_list), self._per_keyword)
        found: list[Candidate] = []
        empty: set[str] = set()
        # По одному запросу на СЛАГ, а не на слово: «react native developer» и
        # «mobile developer» ведут на одну и ту же страницу роли, и второй заход
        # за ней вернул бы те же карточки за ту же цену.
        seen_slugs = {role_slug(kw) for kw in keywords_list}
        queries = []
        for kw in keywords_list:
            sl = role_slug(kw)
            if sl in seen_slugs:
                seen_slugs.discard(sl)
                queries.append(kw)
        for page in range(1, max(1, self._pages) + 1):
            for kw in queries:
                if kw in empty:
                    continue
                self._page.goto(build_jobs_url(kw, self._remote_only, page),
                                wait_until="domcontentloaded")
                cards = self._job_cards()
                if not cards:
                    empty.add(kw)
                    continue
                found += parse_job_cards(cards, limit=per_kw)
                if len(found) >= limit:
                    return found[:limit]
        return found[:limit]


class _LiveCard:
    def __init__(self, title, company, salary, location, href):
        self._d = {"title": title, "company": company, "salary": salary, "location": location}
        self._href = href

    def get_text(self, role):
        return (self._d.get(role) or "").strip()

    def get_href(self):
        return self._href
