"""Wellfound channel: applies to a job via a logged-in browser session.

Automating Wellfound violates its ToS and risks an account ban (accepted by the
user). DOM interaction is isolated in apply_via_page() because selectors drift.
"""
from app.domain.channel import ChannelError, OutreachContent


def apply_via_page(page, job_url: str, content: OutreachContent) -> None:
    page.goto(job_url, wait_until="domcontentloaded")
    apply_btn = page.get_by_role("button", name="Apply")
    if apply_btn.count() == 0:
        raise ChannelError(f"no Apply button on {job_url}")
    apply_btn.first().click()
    page.get_by_placeholder("Write a note…").fill(content.body)
    page.get_by_role("button", name="Submit application").first().click()


class WellfoundChannel:
    name = "wellfound"
    body_limit = None
    needs_subject = False

    def __init__(self, storage_state_path: str, headless: bool = False):
        self._storage_state_path = storage_state_path
        self._headless = headless
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
            self._page.goto("https://wellfound.com/login")
            input("Залогинься в Wellfound в открытом окне, потом нажми Enter здесь...")
            context.storage_state(path=self._storage_state_path)

    def stop(self) -> None:
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def send(self, target: str, content: OutreachContent) -> None:
        if self._page is None:
            raise ChannelError("WellfoundChannel.start() not called")
        apply_via_page(self._page, target.strip(), content)
