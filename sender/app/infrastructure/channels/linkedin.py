"""LinkedIn channel: sends a message to a profile via a logged-in browser session.

Automating LinkedIn violates its ToS and risks an account ban (accepted by the
user). DOM interaction is isolated in fill_and_send() because selectors drift.
"""
from app.domain.channel import ChannelError, InvitePendingError, OutreachContent
from app.domain.candidate import linkedin_action_for_url, post_author_profile_url


# Easy Apply's button carries the class `jobs-apply-button` in every UI language
# (the account may be in Russian: "Простая подача заявки"). External-apply jobs
# ("Подать заявку" / "Apply", which open the company's own site) do NOT have it
# and cannot be automated.
SEL_EASY_APPLY = "button.jobs-apply-button"
# External-apply button (no Easy Apply): a link/button that opens the company site.
# Verified selectors drift; this is best-effort RU+EN and may need live tuning.
SEL_EXTERNAL_APPLY = (
    "a.jobs-apply-button, "
    "a:has-text('Подать заявку'), button:has-text('Подать заявку'), "
    "a:has-text('Apply'), button:has-text('Apply')"
)
# Final submit of the Easy Apply modal, RU + EN.
SEL_APPLY_SUBMIT = ("button:has-text('Отправить заявку'), "
                    "button[aria-label='Отправить заявку'], "
                    "button:has-text('Submit application')")
# Message composer's file picker: LinkedIn renders a hidden <input type=file>;
# the paperclip reveals it (RU "Прикрепить файл" / EN "Attach a file").
SEL_ATTACH_BTN = ("button[aria-label*='Прикрепить' i], "
                  "button[aria-label*='Attach' i]")
SEL_FILE_INPUT = "input[type='file']"

# Profile top-card actions. Verified live 2026-07-09 on a Russian account: the
# actions are <a>/<button> with visible RU text ("Отправить сообщение",
# "Установить контакт"), NOT role=button name="Message" — match by text, RU+EN.
SEL_MESSAGE_BTN = ("a:has-text('Отправить сообщение'), button:has-text('Отправить сообщение'), "
                   "button:has-text('Сообщение'), a:has-text('Message'), button:has-text('Message')")
SEL_CONNECT_BTN = ("a:has-text('Установить контакт'), button:has-text('Установить контакт'), "
                   "a:has-text('Connect'), button:has-text('Connect')")
# Message overlay (LinkedIn msg-form; classes are language-independent).
SEL_MSG_BOX = ("div.msg-form__contenteditable[contenteditable='true'], "
               "[role='textbox'][contenteditable='true']")
SEL_MSG_SEND = "button.msg-form__send-button"

# Connect-with-note flow. Verified live 2026-07-09 (RU account): clicking
# "Установить контакт" opens a modal ("Добавить заметку в приглашение?") whose
# "Персонализировать" button reveals a note field (max 200 chars, in a SHADOW
# DOM — Playwright locators pierce it, raw querySelector does NOT), then
# "Отправить" sends. Free accounts get ~5 personalized invites/month. A file
# can't ride an invite, so the CV is sent only after the person accepts.
SEL_PERSONALIZE = "button:has-text('Персонализировать'), button:has-text('Personalize')"
SEL_NOTE_BOX = "textarea"                       # the modal's only textarea (shadow DOM)
SEL_INVITE_SEND = "button:text-is('Отправить'), button:text-is('Send')"
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


def _send_message(page, content: OutreachContent) -> None:
    """On an already-open profile, open the message overlay, type the body,
    attach the CV, and send. Assumes SEL_MESSAGE_BTN is present."""
    page.locator(SEL_MESSAGE_BTN).first.click()
    box = page.locator(SEL_MSG_BOX)
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


def connect_with_note(page, note: str) -> None:
    """On an already-open profile, send a connection request with a note.
    Assumes SEL_CONNECT_BTN is present. Raises ChannelError if the modal/note
    field can't be reached."""
    # The connect button can sit under the sticky Premium promo, which swallows a
    # normal click; dispatch the click straight to the element to bypass it.
    connect = page.locator(SEL_CONNECT_BTN).first
    connect.scroll_into_view_if_needed()
    connect.dispatch_event("click")
    page.wait_for_timeout(2500)
    if page.locator(SEL_PERSONALIZE).count() == 0:
        raise ChannelError("LinkedIn: модалка приглашения не открылась (нет «Персонализировать»)")
    page.locator(SEL_PERSONALIZE).first.click()
    page.wait_for_timeout(1500)
    box = page.locator(SEL_NOTE_BOX)
    if box.count() == 0:
        raise ChannelError("LinkedIn: поле записки не найдено")
    box.first.fill(note[:_NOTE_LIMIT])
    page.wait_for_timeout(500)
    page.locator(SEL_INVITE_SEND).first.click()
    page.wait_for_timeout(1500)


def message_or_connect(page, profile_url: str, content: OutreachContent) -> None:
    """Message the profile if possible; otherwise send a connection request with
    a note (the post author is usually not a 1st-degree contact, and a file can't
    ride an invite — so the CV goes only after they accept, signalled via
    InvitePendingError)."""
    page.goto(profile_url, wait_until="domcontentloaded")
    if page.locator(SEL_MESSAGE_BTN).count() > 0:
        _send_message(page, content)
    elif page.locator(SEL_CONNECT_BTN).count() > 0:
        connect_with_note(page, content.body)
        raise InvitePendingError(
            f"LinkedIn: отправлен запрос на контакт с запиской — CV дошлём после "
            f"подтверждения: {profile_url}")
    else:
        raise ChannelError(f"LinkedIn: ни «Сообщение», ни «Контакт» не найдены на {profile_url}")


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
        try:
            desc = page.locator("div.jobs-description, main").first.inner_text(timeout=5000)[:6000]
        except Exception:  # noqa: BLE001
            desc = ""
        apply_page = page
        btn = page.locator(SEL_EXTERNAL_APPLY)
        if btn.count() > 0:
            try:
                with page.context.expect_page(timeout=15000) as popup:
                    btn.first.click()
                apply_page = popup.value
            except Exception:  # noqa: BLE001 — same-tab navigation, no popup
                apply_page = page
        fn = self._ext["fn"]
        fn(apply_page, job_url, content,
           profile=self._ext.get("profile"), cv_path=self._ext.get("cv_path", ""),
           answerer=self._ext.get("answerer"), dry_run=self._ext.get("dry_run", False),
           email_channel=self._ext.get("email_channel"),
           subject_maker=self._ext.get("subject_maker"), vacancy_context=desc)
