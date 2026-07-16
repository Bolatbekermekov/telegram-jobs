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


def _button_enabled(loc) -> bool:
    """Non-blocking enabled-check. is_enabled() AUTO-WAITS ~30s when the locator
    matches nothing (Wellfound re-renders the button mid-poll), so guard with
    count() first — which returns instantly — and cap is_enabled() with a short
    timeout for the rare vanish-between-calls race."""
    try:
        return loc.count() > 0 and loc.first.is_enabled(timeout=1500)
    except Exception:  # noqa: BLE001
        return False


def _wait_button_enabled(page, loc, attempts: int, interval_ms: int = 800) -> bool:
    """Poll (bounded) until `loc`'s button is enabled. Wellfound renders Apply/Send
    `disabled` while the page hydrates / after a message is typed."""
    for _ in range(attempts):
        if _button_enabled(loc):
            return True
        page.wait_for_timeout(interval_ms)
    return False


def _apply_disabled_reason(page, job_url: str) -> str:
    """Short note for why the top-level Apply button stayed disabled."""
    try:
        body = (page.locator("body").inner_text(timeout=2500) or "").lower()
    except Exception:  # noqa: BLE001
        body = ""
    if "not accepting applications" in body or "current location" in body:
        return f"Wellfound: работодатель не принимает заявку (локация/таймзона): {job_url}"
    if "no longer active" in body or "no longer accepting" in body or "position filled" in body:
        return f"Wellfound: вакансия закрыта / больше не активна: {job_url}"
    return (f"Wellfound: кнопка Apply заблокирована — отклик недоступен "
            f"(уже откликался / закрыта / не проходишь фильтр): {job_url}")


def _gated_reason(page, job_url: str) -> str:
    """Short note for why the application can't be submitted (Send disabled)."""
    try:
        txt = (page.get_by_role("dialog").first.inner_text(timeout=2000) or "").lower()
    except Exception:  # noqa: BLE001
        txt = ""
    if any(k in txt for k in ("not accepting applications", "current location",
                              "timezone", "relocation", "не принима")):
        return f"Wellfound: работодатель не принимает заявку (локация/таймзона): {job_url}"
    if "already applied" in txt or "you applied" in txt or "ты уже" in txt:
        return f"Wellfound: ты уже откликался на эту вакансию: {job_url}"
    if "profile" in txt and any(k in txt for k in ("complete", "up to date", "verify")):
        return f"Wellfound: требуется дополнить профиль перед откликом: {job_url}"
    return f"Wellfound: подать заявку нельзя — кнопка Send заблокирована: {job_url}"


def _fill_note(page, body: str) -> None:
    """Fill the first EDITABLE message textarea (best-effort).

    Wellfound's apply form has no fixed placeholder — the field is a <textarea>
    inside the dialog (verified live 2026-07-17), and custom-question fields are
    often `disabled`. Only touch an editable one, with a short timeout, so a
    disabled field never blocks the run. No message field at all → just skip.
    """
    for scope in (page.get_by_role("dialog"), page):
        loc = scope.locator("textarea")
        try:
            n = loc.count()
        except Exception:  # noqa: BLE001
            n = 0
        for i in range(n):
            field = loc.nth(i)
            try:
                if not field.is_editable():
                    continue
                field.fill(body, timeout=4000)
                return
            except Exception:  # noqa: BLE001 — try the next textarea
                continue


def apply_via_page(page, job_url: str, content: OutreachContent,
                   dry_run: bool = False) -> None:
    page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
    # Wellfound is a React SPA: the Apply button renders after load, so wait for
    # it instead of an immediate count() (which raced and always saw zero).
    apply_loc = page.get_by_role("button", name="Apply")
    apply_btn = apply_loc.first
    try:
        apply_btn.wait_for(state="visible", timeout=15000)
    except Exception:  # noqa: BLE001 — not logged in / Cloudflare / posting gone
        raise ManualApplyRequired(_no_apply_reason(page, job_url))
    if not _wait_button_enabled(page, apply_loc, attempts=10):
        # Apply is visible but stays `disabled` (job closed, already applied,
        # profile/eligibility filter). Bail fast — never auto-wait 30s on click().
        raise ManualApplyRequired(_apply_disabled_reason(page, job_url))
    apply_btn.click()
    _fill_note(page, content.body)
    # The apply dialog's submit control is "Send application" (verified live).
    send_loc = page.get_by_role("button", name="Send application")
    send = send_loc.first
    try:
        send.wait_for(state="visible", timeout=10000)
    except Exception:  # noqa: BLE001 — modal never opened / different flow
        raise ManualApplyRequired(f"Wellfound: форма отклика не открылась: {job_url}")
    if not _wait_button_enabled(page, send_loc, attempts=5):
        # Send stays disabled => the job is gated (location/timezone, already applied,
        # incomplete profile, unanswered required questions). Hand to a manual apply.
        raise ManualApplyRequired(_gated_reason(page, job_url))
    if dry_run:
        raise ManualApplyRequired(
            f"Wellfound DRY_RUN: заполнено, НЕ отправлено — проверь вручную: {job_url}")
    send.click()


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
