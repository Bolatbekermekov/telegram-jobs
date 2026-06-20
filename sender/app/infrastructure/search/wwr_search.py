"""We Work Remotely searcher via Playwright (real browser, no login).

WWR returns 403 to non-browser HTTP on its search and job-detail pages, but a
real browser loads everything — no Cloudflare challenge and no account needed
(verified live). We browse the reliable category listing pages (the search
endpoint renders inconsistently), filter to relevant roles by title (shared
app.domain.keyword_match, like RemoteOK/Remotive), and read each job's
description from its page for AI scoring. Raw DOM extraction is isolated in
_job_cards / describe so selector drift is easy to fix.
"""
from app.domain.candidate import KIND_JOB, Candidate, normalize_url
from app.domain.keyword_match import title_matches

WWR_BASE_URL = "https://weworkremotely.com"
WWR_CATEGORIES = [
    "remote-full-stack-programming-jobs",
    "remote-front-end-programming-jobs",
    "remote-back-end-programming-jobs",
]
_DESC_SELECTORS = [
    "div.lis-container__job__content__description",
    "[class*='lis-container__job__content__description']",
    "section.listing-container",
]


def build_category_url(slug: str) -> str:
    return f"{WWR_BASE_URL}/categories/{slug}"


def parse_wwr_cards(cards, keywords, limit: int) -> list[Candidate]:
    """Keep cards whose title matches a keyword role word; map to Candidate."""
    out = []
    for card in cards:
        title = card.get_text("title")
        if not title_matches(title, keywords):
            continue
        out.append(Candidate(
            platform="wwr", kind=KIND_JOB, url=card.get_href(),
            title=title, company=card.get_text("company"),
            salary="", location=card.get_text("location"), summary="",
        ))
        if len(out) >= limit:
            break
    return out


class _LiveCard:
    """Adapts a Playwright element's already-read text into the parser interface."""

    def __init__(self, title, company, location, href):
        self._d = {"title": title, "company": company, "location": location}
        self._href = href if str(href).startswith("http") else f"{WWR_BASE_URL}{href}"

    def get_text(self, role):
        return (self._d[role] or "").strip()

    def get_href(self):
        return self._href


class WWRSearcher:
    name = "wwr"

    def __init__(self, categories=None, headless: bool = False):
        # WWR job pages are behind Cloudflare, which only a VISIBLE (headful)
        # browser clears — headless is challenged with "Just a moment". So this
        # searcher runs headful by default and uses patchright (anti-detection).
        self._categories = categories or WWR_CATEGORIES
        self._headless = headless
        self._pw = None
        self._browser = None
        self._page = None

    def start(self) -> None:
        from patchright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        # Real Chrome (channel="chrome"), headful, to pass WWR's Cloudflare; no login.
        self._browser = self._pw.chromium.launch(headless=self._headless, channel="chrome")
        self._page = self._browser.new_context().new_page()

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

    def _job_cards(self):
        cards = []
        for el in self._page.locator("li.new-listing-container").all():
            try:
                href = el.locator("a[href^='/remote-jobs/']").first.get_attribute(
                    "href", timeout=2000)
            except Exception:  # noqa: BLE001
                href = ""
            cards.append(_LiveCard(
                title=self._text(el, ".new-listing__header__title__text"),
                company=self._text(el, ".new-listing__company-name"),
                location=self._text(el, ".new-listing__company-headquarters"),
                href=href,
            ))
        return cards

    def search(self, keywords_list, location, limit) -> list[Candidate]:
        found: list[Candidate] = []
        seen: set[str] = set()
        for slug in self._categories:
            try:
                self._page.goto(build_category_url(slug),
                                wait_until="domcontentloaded", timeout=30000)
                self._page.wait_for_selector("li.new-listing-container", timeout=12000)
            except Exception:  # noqa: BLE001 — one category failing must not kill the rest
                continue
            for c in parse_wwr_cards(self._job_cards(), keywords_list, limit):
                key = normalize_url(c.url)
                if not key or key in seen:
                    continue
                seen.add(key)
                found.append(c)
                if len(found) >= limit:
                    return found
        return found

    def describe(self, url: str) -> str:
        try:
            self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
            # Wait for the description to render (also lets Cloudflare clear).
            try:
                self._page.wait_for_selector(_DESC_SELECTORS[0], timeout=15000)
            except Exception:  # noqa: BLE001
                self._page.wait_for_timeout(5000)
        except Exception:  # noqa: BLE001
            return ""
        for sel in _DESC_SELECTORS:
            try:
                text = self._page.locator(sel).first.inner_text(timeout=3000)
                if len(text.strip()) > 100:
                    return text.strip()[:6000]
            except Exception:  # noqa: BLE001
                continue
        return ""
