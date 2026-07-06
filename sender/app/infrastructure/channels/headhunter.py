"""HeadHunter channel: applies to a vacancy via a logged-in browser session.

hh.ru closed its applicant API on 2025-12-15, so UI automation is the only
working path. Automating hh.ru violates its ToS and risks an account ban
(accepted by the user). Stock Playwright is fingerprinted by hh.ru's
anti-bot, so we use patchright + the real Chrome channel (same as Wellfound).
DOM interaction is isolated in apply_via_page() because selectors drift.
"""
import re

from app.domain.channel import ChannelError, OutreachContent, RateLimitedError

_VACANCY_RE = re.compile(r"hh\.(?:ru|kz)/vacancy/(\d+)")

# hh.ru data-qa hooks (verified live in Task 8; fix HERE when they drift).
SEL_APPLY = "[data-qa='vacancy-response-link-top']"
SEL_ALREADY_APPLIED = "[data-qa='vacancy-response-link-view-topic']"
SEL_RELOCATION_CONFIRM = "[data-qa='relocation-warning-confirm']"
SEL_LETTER_TOGGLE = "[data-qa='vacancy-response-letter-toggle']"
SEL_LETTER_INPUT = "[data-qa='vacancy-response-popup-form-letter-input']"
SEL_SUBMIT = "[data-qa='vacancy-response-submit-popup']"
_LOGIN_MARKERS = ("/account/login", "/login", "captcha")


def extract_vacancy_id(target: str) -> str:
    t = target.strip()
    if t.isdigit():
        return t
    m = _VACANCY_RE.search(t)
    if not m:
        raise ChannelError(f"cannot extract hh.ru vacancy id from: {target}")
    return m.group(1)


def vacancy_url(target: str) -> str:
    return f"https://hh.ru/vacancy/{extract_vacancy_id(target)}"


def _check_not_blocked(page) -> None:
    if any(marker in page.url for marker in _LOGIN_MARKERS):
        raise RateLimitedError(f"hh.ru asks to log in / solve captcha: {page.url}")


def apply_via_page(page, url: str, content: OutreachContent) -> None:
    page.goto(url, wait_until="domcontentloaded")
    _check_not_blocked(page)
    if page.locator(SEL_ALREADY_APPLIED).count() > 0:
        raise ChannelError(f"already applied: {url}")
    apply_btn = page.locator(SEL_APPLY)
    if apply_btn.count() == 0:
        raise ChannelError(f"no apply button on {url}")
    apply_btn.first.click()
    _check_not_blocked(page)
    # Foreign-vacancy confirmation popup ("вакансия в другой стране") — optional.
    if page.locator(SEL_RELOCATION_CONFIRM).count() > 0:
        page.locator(SEL_RELOCATION_CONFIRM).first.click()
    # The cover-letter textarea may need expanding first — also optional.
    if page.locator(SEL_LETTER_TOGGLE).count() > 0:
        page.locator(SEL_LETTER_TOGGLE).first.click()
    page.locator(SEL_LETTER_INPUT).first.fill(content.body)
    page.locator(SEL_SUBMIT).first.click()


class HeadHunterChannel:
    name = "hh"
    body_limit = 10000          # hh.ru cover-letter length limit
    needs_subject = False

    def __init__(self, storage_state_path: str, headless: bool = False):
        self._storage_state_path = storage_state_path
        self._headless = headless
        self._pw = None
        self._browser = None
        self._page = None

    def start(self) -> None:
        from pathlib import Path

        from patchright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._headless, channel="chrome")
        state = self._storage_state_path if Path(self._storage_state_path).exists() else None
        context = self._browser.new_context(storage_state=state, no_viewport=True)
        self._page = context.new_page()
        if state is None:
            self._page.goto("https://hh.ru/account/login")
            input("Залогинься в hh.ru в открытом окне, потом нажми Enter здесь...")
            context.storage_state(path=self._storage_state_path)

    def stop(self) -> None:
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def send(self, target: str, content: OutreachContent) -> None:
        if self._page is None:
            raise ChannelError("HeadHunterChannel.start() not called")
        apply_via_page(self._page, vacancy_url(target), content)
