"""LinkedIn channel: sends a message to a profile via a logged-in browser session.

Automating LinkedIn violates its ToS and risks an account ban (accepted by the
user). DOM interaction is isolated in fill_and_send() because selectors drift.
"""
from app.domain.channel import (
    ChannelError, ChannelUnavailable, InvitePendingError, ManualApplyRequired,
    OutreachContent, RateLimitedError,
)
from app.domain.candidate import linkedin_action_for_url, post_author_profile_url


# Easy Apply's button carries the class `jobs-apply-button` in every UI language
# (the account may be in Russian: "Простая подача заявки"). External-apply jobs
# ("Подать заявку" / "Apply", which open the company's own site) do NOT have it
# and cannot be automated.
SEL_EASY_APPLY = "button.jobs-apply-button"
# Final submit of the Easy Apply modal, RU + EN.
SEL_APPLY_SUBMIT = ("button:has-text('Отправить заявку'), "
                    "button[aria-label='Отправить заявку'], "
                    "button:has-text('Submit application')")
# Message composer's file picker: LinkedIn renders a hidden <input type=file>;
# the paperclip reveals it (RU "Прикрепить файл" / EN "Attach a file").
SEL_ATTACH_BTN = ("button[aria-label*='Прикрепить' i], "
                  "button[aria-label*='Attach' i]")
SEL_FILE_INPUT = "input[type='file']"

# Profile top-card actions. Verified live 2026-07-21 on a Russian account.
# Scoping is the whole battle here: the "Больше профилей"/"Изучите профили Premium"
# recommendation cards live in the SAME <main> as the profile (not a separate
# <aside>), each with its own Connect/Follow/«Еще» for OTHER people, and they are
# interleaved by DOM order — so neither `main …` nor `.first` nor
# `section:first-of-type` (which matches 9 nested sections) isolates the profile.
# The one thing unique to the profile's own action bar is the message-compose
# link (recommendation cards only Connect/Follow), so anchor on the section that
# holds it. Verified live: this section starts with the profile's name/headline
# and carries none of the recommendation Connects.
_TOPCARD = "section:has(a[href*='/messaging/compose/'])"
# The message-compose link — unique to the profile's own action bar (recommendation
# cards only Connect/Follow), so it anchors both the message action and the
# top-card Connect below.
SEL_COMPOSE = "a[href*='/messaging/compose/']"
# Message path opens the compose link; .first is the profile's (aria-label is
# empty, so we key on the href — a text match also catches feed posts / the
# bottom messaging launcher).
SEL_MESSAGE_BTN = (f"{SEL_COMPOSE}, "
                   f"{_TOPCARD} button:has-text('Отправить сообщение'), "
                   f"{_TOPCARD} button:has-text('Message')")
# Text of a Connect control (RU «Установить контакт» / EN Connect). A 2nd-degree
# profile shows it as a primary <a> in the action bar (aria-label «Пригласить
# участника <name>», text «Установить контакт»). Applied ONLY within the compose
# link's action bar (see _topcard_connect): unscoped it also matches every
# recommendation card's Connect, which carry the same text and differ only by name.
SEL_CONNECT_TEXT = ("a:has-text('Установить контакт'), button:has-text('Установить контакт'), "
                    "a:has-text('Connect'), button:has-text('Connect')")
# The "…"/"Еще" overflow button on the top card, and the Connect entry inside it.
# For a 3rd-degree profile the only Connect action lives in this menu (verified
# live 2026-07-21: the menu item is an <a role="menuitem">, not a button). The
# opened dropdown renders in a body-level portal OUTSIDE the section, so
# SEL_MENU_CONNECT stays unscoped — but role='menuitem' already excludes the
# recommendation cards' <button>s.
SEL_MORE_BTN = f"{_TOPCARD} button[aria-label='Еще'], {_TOPCARD} button[aria-label='More']"
SEL_MENU_CONNECT = ("a[role='menuitem']:has-text('Установить контакт'), "
                    "a[role='menuitem']:has-text('Connect')")
# Message overlay (LinkedIn msg-form; classes are language-independent).
SEL_MSG_BOX = ("div.msg-form__contenteditable[contenteditable='true'], "
               "[role='textbox'][contenteditable='true']")
SEL_MSG_SEND = "button.msg-form__send-button"

# Connect-with-note flow. Verified live 2026-07-09 (RU account): clicking
# "Установить контакт" opens a modal ("Добавить заметку в приглашение?") whose
# "Персонализировать" button reveals a note field (max 200 chars, in a SHADOW
# DOM — Playwright locators pierce it, raw querySelector does NOT), then
# "Отправить" sends. Free accounts get ~5 personalized invites/month. A file
# can't ride an invite, and we deliberately do NOT chase the person to send a CV
# once they accept — that lands out of context (they often reply first), so the
# connection request + cover-letter note is the whole outreach; the CV goes only
# when we can message directly (an existing 1st-degree connection).
SEL_PERSONALIZE = "button:has-text('Персонализировать'), button:has-text('Personalize')"
SEL_NOTE_BOX = "textarea"                       # the modal's only textarea (shadow DOM)
# The send button reads "Отправить" but its accessible label is the fuller
# "Отправить приглашение" — :text-is misses it (nested markup gives it no exact
# own-text), so match the aria-label, with a dialog-scoped text fallback. At this
# stage the only other buttons are Пропустить/Отмена, so has-text can't stray.
SEL_INVITE_SEND = ("button[aria-label*='Отправить пригла'], button[aria-label*='Send invit'], "
                   "[role='dialog'] button:has-text('Отправить'), [role='dialog'] button:has-text('Send')")
# When a free account's monthly personalized-invite quota is spent, clicking
# "Персонализировать" shows a Premium upsell ("Вы использовали все свои ежемесячные
# персонализированные приглашения") instead of the note field — so the note (our
# cover letter) can't be attached at all. Detected to stop the platform for the
# run rather than send note-less invites (verified live 2026-07-22).
SEL_INVITE_LIMIT = "text=/персонализированны[хе] приглашени|personalized invitation/i"
_NOTE_LIMIT = 200


def _attach_cv(page, path: str) -> None:
    """Attach the CV file to the open message thread. Fails loudly if the file
    input never appears — better to skip the lead than send a CV-less message."""
    file_input = page.locator(SEL_FILE_INPUT)
    if file_input.count() == 0:
        btn = page.locator(SEL_ATTACH_BTN)
        if btn.count() > 0:
            btn.first.click()
            page.wait_for_timeout(500)
        file_input = page.locator(SEL_FILE_INPUT)
    if file_input.count() == 0:
        raise ChannelError("LinkedIn: не нашёл поле вложения — CV не прикреплён")
    file_input.first.set_input_files(path)
    page.wait_for_timeout(2000)  # let the upload chip render before sending


def _click_via_dom(locator) -> None:
    """Click via an in-page native HTMLElement.click() on the element.

    This is the only technique that works for LinkedIn's top-card buttons
    (verified live 2026-07-21):
    * A plain Playwright .click() times out — the top nav layer sits over the
      button after scroll-into-view and intercepts the pointer (the row-79
      "intercepts pointer events" 30s timeout).
    * scroll_into_view_if_needed() then errors "element not attached" because
      React re-renders the card and detaches the scrolled handle.
    * dispatch_event("click") fires a synthetic event the SPA ignores, so the
      «Еще» menu's "Установить контакт" never opens the invite modal.
    A native el.click() needs no hit-point and no scroll, and drives the SPA
    handler, so the menu opens and the invite modal appears. Bounded timeout:
    the top card re-renders, so a stale match should fail fast and be retried,
    not hang the default 30s."""
    locator.evaluate("el => el.click()", timeout=8000)


def _settle(page) -> None:
    """Let the profile finish rendering before we touch the top-card actions.
    The card mounts client-side after domcontentloaded, and acting too early is
    what detached handles and raced with the sticky nav."""
    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:  # noqa: BLE001 — a busy feed may never idle; the pause still helps
        pass
    page.wait_for_timeout(1500)


def _send_message(page, content: OutreachContent) -> None:
    """On an already-open profile, open the message overlay, type the body,
    attach the CV, and send. Assumes SEL_MESSAGE_BTN is present.

    Only call this for a contact who can actually be messaged for free (see
    message_or_connect): for a non-contact the same button opens the paid InMail
    paywall and no composer appears — guarded here as a manual-apply, never a
    silent no-op."""
    _click_via_dom(page.locator(SEL_MESSAGE_BTN).first)
    page.wait_for_timeout(1500)
    box = page.locator(SEL_MSG_BOX)
    if box.count() == 0:
        raise ManualApplyRequired(
            "LinkedIn: сообщение доступно только через InMail (Premium) — "
            "нужен ручной отклик")
    box.last.click()
    box.last.fill(content.body)
    if content.attachment_path:
        _attach_cv(page, content.attachment_path)
    send = page.locator(SEL_MSG_SEND)
    if send.count() > 0:
        send.first.click()
    else:
        page.keyboard.press("Enter")


def fill_and_send(page, profile_url: str, content: OutreachContent) -> None:
    """Open a profile and message it (RU + EN), attaching the CV. Raises if the
    profile has no message action (not a connection / can't be messaged)."""
    page.goto(profile_url, wait_until="domcontentloaded")
    if page.locator(SEL_MESSAGE_BTN).count() == 0:
        raise ChannelError(f"нет кнопки «Сообщение» на {profile_url} (не в контактах?)")
    _send_message(page, content)


def _visible(page, selector, timeout=5000) -> bool:
    """True once `selector` is visible within `timeout`, False on timeout.
    Condition-based wait — LinkedIn renders menus/modals asynchronously, so a
    fixed pause either races the render or wastes time."""
    try:
        page.locator(selector).first.wait_for(state="visible", timeout=timeout)
        return True
    except Exception:  # noqa: BLE001 — a timeout means "not there", not a crash
        return False


def _click_connect_and_wait(page, locator) -> bool:
    """Click a Connect control and confirm the invite modal opened, retrying the
    click once — the SPA occasionally drops the first synthetic click."""
    for attempt in range(2):
        try:
            _click_via_dom(locator)
        except Exception:  # noqa: BLE001 — re-render detached the handle; retry
            pass
        if _visible(page, SEL_PERSONALIZE, timeout=5000):
            return True
        if attempt == 0:
            page.wait_for_timeout(800)
    return False


def _open_more_menu(page) -> bool:
    """Open the top-card "…"/Еще menu and wait for its Connect entry to appear.
    Retries the click once (the card re-renders, so the first native click can
    hit a detaching handle). False means no Connect entry surfaced — a 1st-degree
    contact whose menu offers "Удалить контакт" instead."""
    for attempt in range(2):
        try:
            _click_via_dom(page.locator(SEL_MORE_BTN).first)
        except Exception:  # noqa: BLE001 — stale handle; the retry re-resolves it
            pass
        if _visible(page, SEL_MENU_CONNECT, timeout=4000):
            return True
        page.wait_for_timeout(800)
    return False


def _topcard_connect(page):
    """The profile's OWN top-card Connect control, or None if it has none.

    A 2nd-degree profile shows Connect as a primary action-bar control. It can't
    be matched by text alone — the "Больше профилей" recommendation cards share
    the same <main> and the same «Установить контакт» text/«Пригласить участника»
    aria-label, differing only by name. What is unique to the profile's own action
    bar is the message-compose link (recommendation cards have none), so anchor on
    it: the Connect is a sibling within the compose link's button row (its 2nd DOM
    ancestor). Verified live 2026-07-21 on a 2nd-degree profile — count 1, the
    profile owner's own Connect."""
    compose = page.locator(SEL_COMPOSE)
    if compose.count() == 0:
        return None
    bar = compose.first.locator("xpath=ancestor::*[2]")
    connect = bar.locator(SEL_CONNECT_TEXT)
    return connect if connect.count() > 0 else None


def _open_invite_modal(page) -> bool:
    """Open the "Установить контакт"/invite modal for the profile.

    Returns True on success, False when there is no Connect action at all — a
    1st-degree contact (already connected), so the caller messages instead. Raises
    ChannelError if a Connect action exists but its modal won't open (a transient
    failure to surface as `failed` and retry, NOT a silent fall-through to InMail).

    Two shapes, verified live 2026-07-21:
    * 2nd-degree — Connect is a primary control in the top-card action bar
      (_topcard_connect anchors it past the recommendation cards).
    * 3rd-degree — Connect hides in the "…"/Еше overflow menu, which opens as a
      body-level portal holding only this profile's actions, so its menu item is
      unambiguous.
    The top-card Connect is used ONLY through the compose-link anchor; matched by
    bare text it hits the recommendation cards' Connects for other people."""
    top = _topcard_connect(page)
    if top is not None:
        if _click_connect_and_wait(page, top.first):
            return True
        raise ChannelError("LinkedIn: «Установить контакт» не открыл модалку приглашения")
    if page.locator(SEL_MORE_BTN).count() == 0:
        return False
    # No Connect entry in the menu means a 1st-degree contact — close the menu we
    # opened so it can't sit over the message button, and message instead.
    if not _open_more_menu(page):
        page.keyboard.press("Escape")
        return False
    if _click_connect_and_wait(page, page.locator(SEL_MENU_CONNECT).first):
        return True
    raise ChannelError("LinkedIn: пункт «Установить контакт» не открыл модалку приглашения")


def _fill_invite_note(page, note: str) -> None:
    """With the invite modal open, add a personalized note and send it. Raises
    ChannelError if the modal/note field can't be reached."""
    if page.locator(SEL_PERSONALIZE).count() == 0:
        raise ChannelError("LinkedIn: модалка приглашения не открылась (нет «Персонализировать»)")
    page.locator(SEL_PERSONALIZE).first.click()
    page.wait_for_timeout(1500)
    box = page.locator(SEL_NOTE_BOX)
    if box.count() == 0:
        # No note field after "Персонализировать" usually means the monthly
        # personalized-invite quota is spent (a Premium upsell shows instead). It's
        # account-wide, so every further connect this run would fail the same way —
        # stop the platform (leads stay `new`, retry next month) rather than send
        # note-less invites that drop our cover letter.
        if page.locator(SEL_INVITE_LIMIT).count() > 0:
            raise RateLimitedError(
                "LinkedIn: исчерпан месячный лимит персональных приглашений — "
                "остальные LinkedIn-коннекты на следующий месяц")
        raise ChannelError("LinkedIn: поле записки не найдено")
    box.first.fill(note[:_NOTE_LIMIT])
    page.wait_for_timeout(500)
    page.locator(SEL_INVITE_SEND).first.click()
    page.wait_for_timeout(1500)


def connect_with_note(page, note: str) -> None:
    """On an already-open profile, send a connection request with a note. Reaches
    Connect via the top card or the "…"/Еще menu. Raises if no Connect action
    exists or the note modal can't be reached."""
    if not _open_invite_modal(page):
        raise ChannelError("LinkedIn: действие «Установить контакт» не найдено на профиле")
    _fill_invite_note(page, note)


def message_or_connect(page, profile_url: str, content: OutreachContent) -> None:
    """Reach out to a profile. Prefer a connection request with a note whenever a
    Connect action exists — a non-contact can only be *messaged* via paid InMail,
    but a free invite carries the same cover letter. That invite IS the whole
    outreach (signalled via InvitePendingError): no CV rides an invite and we do
    not chase a CV afterwards — it lands out of context. Only a 1st-degree contact
    (no Connect action anywhere) is messaged directly, and there the CV is sent."""
    page.goto(profile_url, wait_until="domcontentloaded")
    _settle(page)
    if _open_invite_modal(page):
        _fill_invite_note(page, content.body)
        raise InvitePendingError(
            f"LinkedIn: отправлен запрос на контакт с сопроводительным письмом: {profile_url}")
    if page.locator(SEL_MESSAGE_BTN).count() > 0:
        _send_message(page, content)
        return
    raise ChannelError(f"LinkedIn: ни «Сообщение», ни «Контакт» не найдены на {profile_url}")


# LinkedIn's Voyager API holds an offsite job's real apply target as
# `companyApplyUrl`. We read it directly (an in-page fetch carries the logged-in
# session + csrf) instead of clicking the "apply on the company site" button,
# which — like the now-removed jobs-apply-button class — does NOT navigate under
# browser automation.
_VOYAGER_APPLY_JS = r"""
async (jobUrl) => {
  const m = (jobUrl || location.pathname).match(/jobs\/view\/(\d+)/);
  if (!m) return null;
  const jobId = m[1];
  const csrf = (document.cookie.match(/JSESSIONID="?([^";]+)"?/) || [])[1] || '';
  const deco = 'com.linkedin.voyager.deco.jobs.web.shared.WebFullJobPosting-65';
  let txt = '';
  try {
    let r = await fetch(`/voyager/api/jobs/jobPostings/${jobId}?decorationId=${deco}`,
      {headers: {'csrf-token': csrf,
                 'accept': 'application/vnd.linkedin.normalized+json+2.1'}});
    if (r.status !== 200)
      r = await fetch(`/voyager/api/jobs/jobPostings/${jobId}`, {headers: {'csrf-token': csrf}});
    txt = await r.text();
  } catch (e) { return null; }
  const mm = txt.match(/"companyApplyUrl"\s*:\s*("(?:[^"\\]|\\.)*")/);
  if (!mm) return null;
  try { return JSON.parse(mm[1]); } catch (e) { return null; }
}
"""


def fetch_company_apply_url(page, job_url):
    """Return an offsite LinkedIn job's real company apply URL, or None if it is
    not an offsite apply (e.g. Easy Apply) or cannot be read. Uses LinkedIn's
    Voyager API via an in-page fetch, so it runs with the logged-in session."""
    try:
        return page.evaluate(_VOYAGER_APPLY_JS, job_url)
    except Exception:  # noqa: BLE001
        return None


class _ExternalApplyNeeded(Exception):
    """Internal: this LinkedIn job has no Easy Apply; the caller runs external apply."""


def easy_apply_via_page(page, job_url: str, content: OutreachContent) -> None:
    """Open a job and submit via Easy Apply. Raises _ExternalApplyNeeded when the
    job's only route is an external company site (handled by the channel)."""
    page.goto(job_url, wait_until="domcontentloaded")
    apply_btn = page.locator(SEL_EASY_APPLY)
    if apply_btn.count() == 0:
        raise _ExternalApplyNeeded()
    apply_btn.first.click()
    # A single-step Easy Apply shows the submit button right away. Multi-step
    # forms (contact → resume → questions) don't, and can't be auto-completed —
    # surface that clearly instead of leaving a half-filled application.
    submit = page.locator(SEL_APPLY_SUBMIT)
    if submit.count() == 0:
        raise ChannelError(
            f"LinkedIn Easy Apply многошаговый, нужен ручной отклик: {job_url}")
    submit.first.click()


class LinkedInChannel:
    name = "linkedin"
    body_limit = 300          # safe for connection notes; messages allow more
    needs_subject = False

    def __init__(self, storage_state_path: str, headless: bool = False,
                 external_apply_deps=None):
        self._storage_state_path = storage_state_path
        self._headless = headless
        # {"enabled": bool, "fn": callable, plus kwargs profile/cv_path/answerer/
        #  dry_run/email_channel/subject_maker} — built in the registry.
        self._ext = external_apply_deps or {"enabled": False, "fn": None}
        self._pw = None
        self._browser = None
        self._page = None

    def start(self) -> None:
        from playwright.sync_api import sync_playwright

        from app.infrastructure.linkedin_session import has_valid_session

        # Guard before launching anything: a state file that exists but has no live
        # `li_at` browses as a guest, and LinkedIn bounces every profile to the
        # authwall (no Message/Connect button) — which used to surface as every
        # LinkedIn lead failing with "ни «Сообщение», ни «Контакт»". Stop the run
        # cleanly with a re-login hint instead. Login itself is `make login_browser`,
        # never done mid-run (mirrors the Telegram channel's authorisation check).
        if not has_valid_session(self._storage_state_path):
            raise ChannelUnavailable(
                "сессия LinkedIn недействительна или отсутствует (нет живого li_at) — "
                "выполни `make login_browser` и залогинься заново")

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._headless)
        context = self._browser.new_context(storage_state=self._storage_state_path)
        self._page = context.new_page()

    def stop(self) -> None:
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def send(self, target: str, content: OutreachContent) -> None:
        if self._page is None:
            raise ChannelError("LinkedInChannel.start() not called")
        target = target.strip()
        action = linkedin_action_for_url(target)
        if action == "easy_apply":
            try:
                easy_apply_via_page(self._page, target, content)
            except _ExternalApplyNeeded:
                self._external_apply(target, content)
            return
        if action == "post":
            # A hiring post: message its author (id is embedded in the post URL).
            author = post_author_profile_url(target)
            if not author:
                raise ChannelError(f"LinkedIn пост: не удалось определить автора: {target}")
            target = author
        message_or_connect(self._page, target, content)

    def _external_apply(self, job_url: str, content: OutreachContent) -> None:
        if not self._ext.get("enabled") or self._ext.get("fn") is None:
            raise ChannelError(
                f"внешний отклик LinkedIn (не Easy Apply), нужен ручной отклик: {job_url}")
        page = self._page
        # Grab the LinkedIn job description for AI context BEFORE navigating away.
        try:
            desc = page.locator("main").first.inner_text(timeout=5000)[:6000]
        except Exception:  # noqa: BLE001
            desc = ""
        # Read the company's real apply URL from LinkedIn's Voyager API and go
        # straight there — the on-page "apply on the company site" button does not
        # navigate under automation, so we never rely on clicking it.
        company_url = fetch_company_apply_url(page, job_url)
        if not company_url:
            raise ManualApplyRequired(
                f"LinkedIn: нет ссылки внешнего отклика (возможно Easy Apply): {job_url}")
        page.goto(company_url, wait_until="domcontentloaded")
        fn = self._ext["fn"]
        fn(page, job_url, content,
           profile=self._ext.get("profile"), cv_path=self._ext.get("cv_path", ""),
           answerer=self._ext.get("answerer"), dry_run=self._ext.get("dry_run", False),
           email_channel=self._ext.get("email_channel"),
           subject_maker=self._ext.get("subject_maker"), vacancy_context=desc)
