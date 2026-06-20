"""LinkedIn vacancy/recruiter search via a logged-in Playwright session.

Automating LinkedIn violates its ToS and risks an account ban (accepted by the
user). Raw DOM extraction is isolated in parse_* (selectors drift); the class
collects "card" wrappers and hands them to the pure parsers.
"""
from urllib.parse import urlencode

from app.domain.candidate import Candidate, KIND_JOB, KIND_PROFILE


def build_jobs_url(keywords: str, location: str) -> str:
    qs = urlencode({
        "keywords": keywords,
        "location": location,
        "f_E": "1,2",       # 1=Internship, 2=Entry level
        "f_WT": "2",        # Remote
        "f_TPR": "r86400",  # posted in the last 24h
    })
    return f"https://www.linkedin.com/jobs/search/?{qs}"


def build_people_url(keywords: str) -> str:
    qs = urlencode({"keywords": keywords})
    return f"https://www.linkedin.com/search/results/people/?{qs}"


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
                 people_enabled: bool = False):
        self._storage_state_path = storage_state_path
        self._headless = headless
        self._people_enabled = people_enabled
        self._pw = None
        self._browser = None
        self._page = None

    def start(self) -> None:
        from pathlib import Path

        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._headless)
        state = self._storage_state_path if Path(self._storage_state_path).exists() else None
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
        """Return card wrappers exposing get_text(role)/get_href(). Selectors here.

        LinkedIn moved job-card fields onto the shared `artdeco-entity-lockup__*`
        classes; the title is duplicated by a visually-hidden a11y span, so we keep
        only the first line.
        """
        cards = []
        for el in self._page.locator("div.job-card-container").all():
            try:
                href = el.locator("a.job-card-container__link").first.get_attribute(
                    "href", timeout=2000)
            except Exception:  # noqa: BLE001
                href = ""
            cards.append(_LiveCard(
                title=self._text(el, ".artdeco-entity-lockup__title").split("\n")[0],
                company=self._text(el, ".artdeco-entity-lockup__subtitle"),
                location=self._text(el, ".artdeco-entity-lockup__caption"),
                href=href,
            ))
        return cards

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
        found: list[Candidate] = []
        for kw in keywords_list:
            self._page.goto(build_jobs_url(kw, location), wait_until="domcontentloaded")
            found += parse_job_cards(self._job_cards(), limit=limit)
            if self._people_enabled:
                self._page.goto(build_people_url(kw), wait_until="domcontentloaded")
                found += parse_people_cards(self._people_cards(), limit=limit)
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
