"""Threads channel: DMs the post author from a saved (burner) session.

This is the FALLBACK, not the main path. Priority is always the real contact found
inside the thread — a recruiter who posts a vacancy says how to reach them, and
that contact is usually Telegram or email, handled by the existing channels.

Two things to know about a Threads DM:
  * it carries text, photos, video, GIFs and stickers — NO documents, so the CV
    cannot be attached. `attachment_path` is dropped on purpose; the signature
    (added by code, not the model) already carries Telegram and email.
  * a DM to someone who does not follow you lands in their "message requests",
    which recruiters rarely open. Delivery here is genuinely weak, which is why
    this is the last resort.

Threads runs on an Instagram account, so automating it risks that Instagram
account (accepted by the user, on a separate burner account). Selectors drift, so
DOM interaction is confined to _deliver().
"""
import re

from app.domain.channel import (
    ChannelError,
    ChannelUnavailable,
    ManualApplyRequired,
    OutreachContent,
)
from app.infrastructure.threads_session import has_valid_session

# Threads posts cap at 500 characters. The DM limit is not documented and was not
# measured; 500 is the conservative floor. Raise it only after checking live.
_BODY_LIMIT = 500

_HANDLE_RE = re.compile(
    r"(?:https?://)?(?:www\.)?threads\.(?:com|net)/@?([\w.]+)", re.IGNORECASE)


def normalize_target(target: str) -> str:
    """'@nick', 'nick', 'https://www.threads.com/@nick' -> 'nick'."""
    t = (target or "").strip()
    m = _HANDLE_RE.match(t)
    if m:
        t = m.group(1)
    return t.lstrip("@")


class ThreadsChannel:
    name = "threads"
    body_limit = _BODY_LIMIT
    needs_subject = False

    def __init__(self, state_path: str, headless: bool = False):
        self._state_path = state_path
        self._headless = headless
        self._pw = None
        self._browser = None
        self._page = None

    def start(self) -> None:
        # Guard before launching anything, exactly as the LinkedIn channel does: a
        # state file with no live `sessionid` browses as a guest and every DM dies
        # on the login wall. Login is `make login_threads`, never done mid-run.
        if not has_valid_session(self._state_path):
            raise ChannelUnavailable(
                "сессия Threads недействительна или отсутствует (нет живого "
                "sessionid) — выполни `make login_threads` и залогинься заново")

        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._headless)
        self._page = self._browser.new_context(
            storage_state=self._state_path).new_page()

    def stop(self) -> None:
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def send(self, target: str, content: OutreachContent) -> None:
        handle = normalize_target(target)
        if not handle:
            raise ChannelError(f"не разобрал хендл Threads из '{target}'")
        # content.attachment_path is intentionally ignored: see module docstring.
        self._deliver(handle, content.body)

    def _deliver(self, handle: str, body: str) -> None:
        """Open the DM composer for `handle` and send `body`.

        Not implemented yet, and deliberately so: the composer's DOM cannot be read
        without a logged-in Threads account, and this project pins selectors from
        the live page with the date they were captured rather than guessing them.
        This is the one place in the feature whose DOM was not verifiable up front.

        `ManualApplyRequired`, not `NotImplementedError`: this is exactly the case
        that exception names — the outreach could not be automated, so a human does
        it by hand — and it is the one `SendOutreach` maps to `manual`, which is
        what the lead must land on. A bare `NotImplementedError` would fall through
        to the generic handler and be recorded as an ordinary failure.
        """
        raise ManualApplyRequired(
            "DM-композер Threads ещё не автоматизирован: его селекторы снимаются "
            "только с живой страницы под залогиненным аккаунтом, а гадать их в "
            "этом проекте нельзя. Что закрывает: `make login_threads` на отдельном "
            "(burner) Instagram, дальше Task 10 фиксирует селекторы. Пока — напиши "
            f"автору вручную: @{handle}")
