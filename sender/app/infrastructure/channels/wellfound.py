"""Wellfound channel: applies to a job through the user's warm, logged-in Chrome.

Wellfound sits behind Cloudflare Turnstile, whose clearance is bound to the
browser that solved it — a separately launched browser (stock Playwright OR
patchright) just loops on the challenge. So, exactly like the Wellfound searcher,
the apply channel ATTACHES over CDP to the real Chrome the user opened with
`make login_wellfound` (already past Cloudflare and logged in) and drives the
apply there. It never launches its own browser, and never touches wellfound_state.json.

Automating Wellfound violates its ToS and risks an account ban (accepted by the
user). DOM interaction is isolated in apply_via_page() because selectors drift.
"""
from app.domain.channel import (
    ChannelError,
    ChannelUnavailable,
    ManualApplyRequired,
    OutreachContent,
)


def _no_apply_reason(page, job_url: str) -> str:
    """A short, categorised note for why the Apply button never appeared."""
    try:
        title = (page.title() or "").lower()
    except Exception:  # noqa: BLE001
        title = ""
    try:
        url = (page.url or "").lower()
    except Exception:  # noqa: BLE001
        url = ""
    if "moment" in title or "момент" in title or "challenges.cloudflare" in url:
        return f"Wellfound за Cloudflare — открой make login_wellfound и пройди проверку: {job_url}"
    if "/login" in url or "log in" in title or "sign in" in title:
        return f"Wellfound: не залогинен — сделай make login_wellfound: {job_url}"
    return f"Wellfound: кнопка Apply не найдена (возможно уже подано/закрыто): {job_url}"


def _fill_note(page, body: str) -> None:
    """Best-effort: some Wellfound applications have a message box, some don't."""
    box = page.get_by_placeholder("Write a note…").first
    try:
        box.wait_for(state="visible", timeout=6000)
        box.fill(body)
    except Exception:  # noqa: BLE001 — no note box on this application
        pass


def apply_via_page(page, job_url: str, content: OutreachContent,
                   dry_run: bool = False) -> None:
    page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
    # Wellfound is a React SPA: the Apply button renders after load, so wait for
    # it instead of an immediate count() (which raced and always saw zero).
    apply_btn = page.get_by_role("button", name="Apply").first
    try:
        apply_btn.wait_for(state="visible", timeout=15000)
    except Exception:  # noqa: BLE001 — not logged in / Cloudflare / posting gone
        raise ManualApplyRequired(_no_apply_reason(page, job_url))
    apply_btn.click()
    _fill_note(page, content.body)
    if dry_run:
        raise ManualApplyRequired(
            f"Wellfound DRY_RUN: заполнено, НЕ отправлено — проверь вручную: {job_url}")
    page.get_by_role("button", name="Submit application").first.click()


class WellfoundChannel:
    name = "wellfound"
    body_limit = None
    needs_subject = False

    def __init__(self, cdp_url: str, dry_run: bool = False):
        self._cdp_url = cdp_url
        self._dry_run = dry_run
        self._pw = None
        self._browser = None
        self._page = None

    def start(self) -> None:
        from patchright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        # Attach to the user's already-open, human-driven Chrome (Cloudflare
        # already passed, session logged in). Do NOT launch or re-create context.
        try:
            self._browser = self._pw.chromium.connect_over_cdp(self._cdp_url)
        except Exception as exc:  # noqa: BLE001 — Chrome not running / port closed
            self._pw.stop()
            self._pw = None
            raise ChannelUnavailable(
                "Wellfound Chrome не запущен — сделай make login_wellfound "
                f"и оставь Chrome открытым ({exc})")
        context = (self._browser.contexts[0] if self._browser.contexts
                   else self._browser.new_context())
        self._page = context.pages[0] if context.pages else context.new_page()

    def stop(self) -> None:
        # CDP mode: leave the user's Chrome running; only drop our connection.
        if self._pw:
            self._pw.stop()

    def send(self, target: str, content: OutreachContent) -> None:
        if self._page is None:
            raise ChannelError("WellfoundChannel.start() not called")
        apply_via_page(self._page, target.strip(), content, self._dry_run)
