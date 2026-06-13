"""LinkedIn channel: sends a message to a profile via a logged-in browser session.

Automating LinkedIn violates its ToS and risks an account ban (accepted by the
user). DOM interaction is isolated in fill_and_send() because selectors drift.
"""
from app.domain.channel import ChannelError, OutreachContent


def fill_and_send(page, profile_url: str, content: OutreachContent) -> None:
    """Open a profile and send a message. `page` is a Playwright Page (or a fake)."""
    page.goto(profile_url, wait_until="domcontentloaded")
    msg_btn = page.get_by_role("button", name="Message")
    if msg_btn.count() == 0:
        # Not a 1st-degree connection: a message box is unavailable here.
        raise ChannelError(f"no Message button on {profile_url} (not connected?)")
    msg_btn.first().click()
    page.get_by_label("Write a message…").fill(content.body)
    page.keyboard_press("Enter")


class LinkedInChannel:
    name = "linkedin"
    body_limit = 300          # safe for connection notes; messages allow more
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
            self._page.goto("https://www.linkedin.com/login")
            input("Залогинься в LinkedIn в открытом окне, потом нажми Enter здесь...")
            context.storage_state(path=self._storage_state_path)

    def stop(self) -> None:
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def send(self, target: str, content: OutreachContent) -> None:
        if self._page is None:
            raise ChannelError("LinkedInChannel.start() not called")
        fill_and_send(self._page, target.strip(), content)
