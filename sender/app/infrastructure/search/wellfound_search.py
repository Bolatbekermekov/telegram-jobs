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


def build_jobs_url(keyword: str, remote_only: bool = False) -> str:
    """remote=true раньше был вшит; человек готов к релокации, и офисные
    вакансии отсекать незачем."""
    qs = {"q": keyword}
    if remote_only:
        qs["remote"] = "true"
    qs = urlencode(qs)
    return f"https://wellfound.com/jobs?{qs}"


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
                 remote_only: bool = False):
        self._storage_state_path = storage_state_path
        self._headless = headless
        self._cdp_url = cdp_url
        self._per_keyword = per_keyword
        self._remote_only = remote_only
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

    def _job_cards(self):
        """Flatten Wellfound's company-grouped results into one card per role.

        Each [data-test='StartupResult'] is a startup (company name in its h2)
        with one or more role links (a[href*='/jobs/<id>-...']). The page is a SPA,
        so wait for the cards to render first. Salary/location render as a run-on
        blob per role, so they are left empty (title/company/url are reliable).
        """
        try:
            self._page.wait_for_selector("[data-test='StartupResult']", timeout=15000)
        except Exception:  # noqa: BLE001 — genuinely no results
            return []
        cards = []
        for startup in self._page.locator("[data-test='StartupResult']").all():
            try:
                company = startup.locator("h2").first.inner_text(timeout=2000)
            except Exception:  # noqa: BLE001
                company = ""
            for a in startup.locator("a[href*='/jobs/']").all():
                href = a.get_attribute("href") or ""
                slug = href.split("/jobs/", 1)[1] if "/jobs/" in href else ""
                if not slug[:1].isdigit():   # skip /jobs/home and other nav links
                    continue
                title = a.inner_text().strip()
                if not title:
                    continue
                cards.append(_LiveCard(
                    title=title, company=company, salary="", location="",
                    href=href if href.startswith("http") else f"https://wellfound.com{href}",
                ))
        return cards

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
        from app.domain.search_request import per_keyword_limit
        per_kw = per_keyword_limit(limit, len(keywords_list), self._per_keyword)
        found: list[Candidate] = []
        for kw in keywords_list:
            self._page.goto(build_jobs_url(kw, self._remote_only),
                            wait_until="domcontentloaded")
            found += parse_job_cards(self._job_cards(), limit=per_kw)
        return found[:limit]


class _LiveCard:
    def __init__(self, title, company, salary, location, href):
        self._d = {"title": title, "company": company, "salary": salary, "location": location}
        self._href = href

    def get_text(self, role):
        return (self._d.get(role) or "").strip()

    def get_href(self):
        return self._href
