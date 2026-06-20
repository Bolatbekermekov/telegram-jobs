"""Wellfound vacancy search via a logged-in Playwright session.

Automating Wellfound violates its ToS and risks a ban (accepted by the user).
DOM extraction isolated in parse_job_cards (selectors drift).
"""
from urllib.parse import urlencode

from app.domain.candidate import Candidate, KIND_JOB


def build_jobs_url(keyword: str) -> str:
    qs = urlencode({"q": keyword, "remote": "true"})
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
                 cdp_url: str | None = None):
        self._storage_state_path = storage_state_path
        self._headless = headless
        self._cdp_url = cdp_url
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
        cards = []
        for el in self._page.locator("div.styles_component__job").all():
            href = el.locator("a").first.get_attribute("href")
            cards.append(_LiveCard(
                title=el.locator("a.styles_titleLink__").first.inner_text(),
                company=el.locator("h2").first.inner_text(),
                salary=el.locator(".styles_compensation__").first.inner_text(),
                location=el.locator(".styles_location__").first.inner_text(),
                href=href if str(href).startswith("http") else f"https://wellfound.com{href}",
            ))
        return cards

    def search(self, keywords_list, location, limit) -> list[Candidate]:
        found: list[Candidate] = []
        for kw in keywords_list:
            self._page.goto(build_jobs_url(kw), wait_until="domcontentloaded")
            found += parse_job_cards(self._job_cards(), limit=limit)
        return found[:limit]


class _LiveCard:
    def __init__(self, title, company, salary, location, href):
        self._d = {"title": title, "company": company, "salary": salary, "location": location}
        self._href = href

    def get_text(self, role):
        return (self._d.get(role) or "").strip()

    def get_href(self):
        return self._href
