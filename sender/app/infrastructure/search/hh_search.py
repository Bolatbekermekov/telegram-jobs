"""HeadHunter searcher via a logged-in patchright browser.

hh.ru's applicant API is closed and its pages sit behind an anti-bot that
flags stock Playwright, so we drive real Chrome via patchright with the
session saved by `make login_hh` (shared with the outreach channel). hh.ru's
own query engine does the filtering — we do NOT re-filter titles by keyword
(unlike WWR): relevant vacancies often have Russian titles. Raw DOM
extraction is isolated in _vacancy_cards / parse_hh_cards so selector drift
is easy to fix. start() refuses to run without a saved session instead of
prompting — the worker must never block on input().
"""
from urllib.parse import quote

from app.domain.candidate import KIND_JOB, Candidate, normalize_url
from app.domain.search_request import per_keyword_limit

HH_BASE_URL = "https://hh.ru"
SEARCH_PAGES = 2  # first 1-2 result pages per keyword (spec)

# hh.ru data-qa hooks (verified live in Task 8; fix HERE when they drift).
SEL_CARD = "[data-qa='vacancy-serp__vacancy']"
SEL_TITLE = "[data-qa='serp-item__title']"
SEL_COMPANY = "[data-qa='vacancy-serp__vacancy-employer']"
SEL_SALARY = "[data-qa='vacancy-serp__compensation']"
SEL_ADDRESS = "[data-qa='vacancy-serp__vacancy-address']"
SEL_DESCRIPTION = "[data-qa='vacancy-description']"
_LOGIN_MARKERS = ("/account/login", "captcha")


def build_search_url(query: str, page: int = 0) -> str:
    return f"{HH_BASE_URL}/search/vacancy?text={quote(query)}&page={page}"


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


class HHSearcher:
    name = "hh"

    def __init__(self, storage_state_path: str, headless: bool = False):
        self._storage_state_path = storage_state_path
        self._headless = headless
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

    def search(self, keywords_list, location, limit) -> list[Candidate]:
        found: list[Candidate] = []
        seen: set[str] = set()
        per_kw = per_keyword_limit(limit, len(keywords_list))
        for query in keywords_list:
            kw_found = 0
            for page_n in range(SEARCH_PAGES):
                if kw_found >= per_kw:
                    break
                try:
                    self._page.goto(build_search_url(query, page_n),
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
        try:
            self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
            text = self._page.locator(SEL_DESCRIPTION).first.inner_text(timeout=15000)
            return text.strip()[:6000]
        except Exception:  # noqa: BLE001
            return ""
