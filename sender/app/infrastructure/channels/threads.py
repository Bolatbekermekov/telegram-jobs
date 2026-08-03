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

# A Threads/Instagram username: ASCII letters, digits, dots, underscores, ≤30.
# Case is PRESERVED, not folded: the composer is given what the sheet holds.
_VALID_HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")

# The host is matched with its subdomains but not as a suffix — the leading
# `(?:^|[\s(<])` is what keeps "notthreads.com/@nick" from being read as Threads.
# The subdomain tolerance is slack for a hand-edited cell and NOT a real format.
# An earlier comment here called `m.threads.com` "the phone's share sheet"; that
# was wrong. Measured 2026-07-27: `m.threads.com` and `m.threads.net` are NXDOMAIN
# on the system resolver, on 8.8.8.8 and on 1.1.1.1 alike, while the control
# `m.facebook.com` resolves — Meta runs no `m.` host for Threads at all. The share
# sheet emits `https://www.threads.com/@user/post/<id>?xmt=…`, which is why the
# intake's narrower `(?:www\.)?threads\.(?:com|net)` loses nothing by not matching
# a mobile host. Do not reintroduce the claim, in either app.
# `search`, not `match`, because Источник is hand-editable and a URL can arrive
# inside a sentence; the capture stops at `/`, so a post URL yields the author
# rather than the post id.
_HANDLE_RE = re.compile(
    r"(?:^|[\s(<])(?:https?://)?(?:[\w-]+\.)*threads\.(?:com|net)/@?"
    r"([A-Za-z0-9._]{1,30})",
    re.IGNORECASE)


def normalize_target(target: str) -> str:
    """'@nick', 'nick', 'https://www.threads.com/@nick/post/X' -> 'nick'. "" if unsure.

    Validated, not merely stripped, and the validation is the point. Источник is a
    spreadsheet cell a human edits, so it can hold a post URL, a sentence around a
    URL, two handles, or a note to self. Whatever comes out of here is typed into a
    DM composer as a username, so anything that is not exactly one username shape
    must resolve to "" — `send` raises ChannelError on "", which surfaces the broken
    row instead of messaging whoever the garbage happens to resolve to.

    While `_deliver` is unimplemented every target ends at ManualApplyRequired and
    nothing can be mis-sent; this guard exists so that stops being true safely.
    """
    t = (target or "").strip()
    m = _HANDLE_RE.search(t)
    if m:
        t = m.group(1)
    t = t.lstrip("@")
    return t if _VALID_HANDLE_RE.match(t) else ""


class ThreadsChannel:
    name = "threads"
    body_limit = _BODY_LIMIT
    needs_subject = False
    # ЛС в Threads файлов не принимает — см. докстроку модуля.
    supports_attachment = False

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
        This is the one place in the feature whose DOM was not verifiable up front,
        and it is still open at the end of the feature — the burner Instagram it
        needs does not exist yet. Closing it: `make login_threads`, open the
        composer by hand, pin its selectors here with the date, following
        channels/linkedin.py::fill_and_send.

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
            "(burner) Instagram — аккаунта под это пока нет, поэтому шаг остаётся "
            "открытым намеренно. Пока — напиши "
            f"автору вручную: @{handle}")
