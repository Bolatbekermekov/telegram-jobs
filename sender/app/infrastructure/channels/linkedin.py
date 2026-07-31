"""LinkedIn channel: sends a message to a profile via a logged-in browser session.

Automating LinkedIn violates its ToS and risks an account ban (accepted by the
user). DOM interaction is isolated in fill_and_send() because selectors drift.
"""
import json
import re

from app.domain.channel import (
    ChannelError, ChannelUnavailable, InvitePendingError, InviteWithoutNoteError,
    ManualApplyRequired, OutreachContent, RateLimitedError,
)
from app.domain.candidate import linkedin_action_for_url, post_author_profile_url


# External-apply jobs ("Подать заявку" / "Apply", which open the company's own
# site) carry no Easy Apply entry point and go through _external_apply instead.
# The Easy Apply entry point. Matched by ACCESSIBLE TEXT, never by class:
# `button.jobs-apply-button` matched nothing at all when measured live (2026-07-29,
# two real job pages, 0 hits after 15s of polling), and the class it looked for is
# the one this file already records as removed. What LinkedIn ships now is an <a>,
# not a <button>, and every class on it is a per-build hash (`_2f85a452 e0e4bffc
# …`) — so any class-based selector is dead by construction, not just outdated.
# Both element types stay in the selector: the anchor is what exists today, the
# button is what existed before, and matching both costs nothing.
SEL_EASY_APPLY = (
    "a:has-text('Простая подача заявки'), button:has-text('Простая подача заявки'), "
    "a:has-text('Easy Apply'), button:has-text('Easy Apply'), "
    "a[aria-label*='простой подачи заявки' i], a[aria-label*='Простая подача заявки' i], "
    "button[aria-label*='Easy Apply' i], a[aria-label*='Easy Apply' i]")
# Final submit of the Easy Apply flow, RU + EN.
SEL_APPLY_SUBMIT = ("button:has-text('Отправить заявку'), "
                    "button[aria-label='Отправить заявку'], "
                    "button:has-text('Submit application')")
# Advance one step. The flow measured live is Contact info («Далее») -> Resume
# («Проверить») -> Review -> Submit, so the last screen before submitting is
# reached by a button that says "check", not "next".
#
# Every entry is an EXACT aria-label or an exact button caption. A wildcard was
# tried first — `button[aria-label*='просмотр' i]` — and it matched the job
# page's own «Просмотреть модуль подтвержденного найма», a navigation control
# that never advances anything: the walk then clicked it until it hit the step
# cap. On a page whose furniture is full of apply-ish words, a loose match is not
# a convenience, it is a loop.
SEL_APPLY_NEXT = ("button[aria-label='Перейти к следующему шагу'], "
                  "button[aria-label='Continue to next step'], "
                  "button[aria-label='Проверить заявку'], "
                  "button[aria-label='Review your application'], "
                  "button:has-text('Далее'), button:has-text('Next'), "
                  "button:has-text('Проверить'), button:has-text('Review')")
# What LinkedIn renders when a step refuses to advance ("A resume is required").
SEL_APPLY_ALERT = "[role=alert]"
# Hard cap on the walk. Real flows are 3-5 screens; anything past this is a loop
# we don't understand, and looping forever on a page that submits job applications
# is the one failure mode worth being paranoid about.
_APPLY_MAX_STEPS = 8
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
# An invite already sent and not yet answered. Captured live 2026-07-29 on a
# profile invited days earlier: an <a> reading «На рассмотрении» whose aria-label
# is «На рассмотрении – нажмите, чтобы отозвать приглашение, отправленное
# участнику …». Scoped to the profile's own action bar, like every other top-card
# control here — the recommendation cards carry the same words for other people.
SEL_INVITE_PENDING = (
    f"{_TOPCARD} a:has-text('На рассмотрении'), {_TOPCARD} button:has-text('На рассмотрении'), "
    f"{_TOPCARD} a:has-text('Ожидание'), {_TOPCARD} button:has-text('Ожидание'), "
    f"{_TOPCARD} a:has-text('Pending'), {_TOPCARD} button:has-text('Pending'), "
    f"{_TOPCARD} a[aria-label*='отозвать приглашение' i], "
    f"{_TOPCARD} a[aria-label*='withdraw invitation' i]")
# «Отправить без записки» — the invite modal's own plain-send action. Used when
# the personalized quota is spent: the request still goes out, just without our
# cover letter.
SEL_INVITE_SEND_PLAIN = (
    "[role='dialog'] button:has-text('Отправить без'), "
    "[role='dialog'] button:has-text('Send without'), "
    "button[aria-label*='Отправить без' i], button[aria-label*='Send without' i]")
_NOTE_LIMIT = 200

# Конец предложения: знак, за которым идёт пробел или конец строки. Просмотр
# вперёд обязателен — точка внутри «Atlanti.ai» или «t.me» концом мысли не
# является, а без этого условия записка обрывалась бы ровно на названии продукта.
_SENTENCE_END = re.compile(r"[.!?…](?=\s|$)")


def _trim_to_sentence(text: str, limit: int) -> str:
    """`text`, сокращённый до `limit` символов по границе предложения.

    Письмо пишется прозой на 100-160 слов, и срез по ближайшему пробелу
    заканчивает его на полумысли: именно так лиды 156/160/161/172/177/179
    получили «…Это близко» и «…нужно доводить». Если не влезает даже первое
    предложение, отступаем к границе слова: обрезанное предложение всё равно
    лучше пустой записки, отправлять больше нечего.
    """
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    # Регулярка идёт по ПОЛНОМУ тексту, а не по окну обрезки: `$` в просмотре
    # вперёд означал бы конец окна, и точка, попавшая ровно на границу, сошла бы
    # за конец предложения — «Смотри Atlanti.ai …» с лимитом 15 обрывалось на
    # «Смотри Atlanti.», ровно на середине домена.
    ends = [m.end() for m in _SENTENCE_END.finditer(text) if m.end() <= limit]
    if ends:
        return text[:ends[-1]].rstrip()
    cut = text.rfind(" ", 0, limit)
    return text[:cut].rstrip() if cut > 0 else text[:limit]


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


# How long «Отправить» may stay disabled (the CV upload finishes on LinkedIn's
# clock), and how long the composer may take to empty once it is pressed. Both
# are seconds in practice; together they stay inside the 30s a single Playwright
# action used to burn on its own.
_SEND_ENABLE_TIMEOUT_MS = 15000
_SEND_CONFIRM_TIMEOUT_MS = 15000
_POLL_STEP_MS = 250


def _wait_until(page, predicate, timeout_ms: int) -> bool:
    """Poll `predicate` until it answers True, or `timeout_ms` runs out.

    Playwright has no wait for either condition this file needs — "the button
    stopped being disabled" and "the box went empty" — and the waits it does have
    all go through actionability, which is the very thing that has to be avoided
    here (see _press_send)."""
    waited = 0
    while waited < timeout_ms:
        try:
            if predicate():
                return True
        except Exception:  # noqa: BLE001 — a re-render detaches the handle; retry
            pass
        page.wait_for_timeout(_POLL_STEP_MS)
        waited += _POLL_STEP_MS
    return False


def _press_send(page, composer) -> None:
    """Press «Отправить» on the open composer and confirm the message left it.

    NOT a Playwright .click(). That click needs a hit point inside the viewport,
    and the composer does not always have one. Measured live 2026-07-30 at the
    run's own 1280x720 viewport: the overlay hangs off
    `div.application-outlet__overlay-container`, which is `position: fixed`, on a
    page where scrollHeight == innerHeight — so there is nothing to scroll and
    "scroll it into view" can never change the answer. An open conversation
    bubble sits at y=100..720 with its send button at y=682, but a MINIMISED one
    keeps its full 620px height and slides 572px down, putting the same button at
    y=1254: visible, enabled, stable and permanently unreachable. That is lead
    #160's 30s of «done scrolling / element is outside of the viewport». A native
    el.click() needs no hit point and no scroll, which is why every other control
    in this file already goes through _click_via_dom.

    What a native click gives up is Playwright's actionability, and both halves
    of it have to be paid back by hand:
    * it does not wait for the button to enable — LinkedIn keeps it disabled
      until the CV upload lands, and el.click() on a disabled button is a silent
      no-op;
    * it does not report a click that did nothing. So the send is confirmed, not
      assumed: on a real send the composer clears (verified live — inner_text()
      goes back to '\\n'). Text still sitting there means nothing was delivered,
      and a lead recorded as `sent` with nothing sent is the one outcome worse
      than a failed one.
    """
    send = page.locator(SEL_MSG_SEND)
    if send.count() > 0:
        # `.last`, matching the box that was filled: one bubble is the normal
        # case, but the two must never be able to name different forms.
        target = send.last
        if not _wait_until(page, target.is_enabled, _SEND_ENABLE_TIMEOUT_MS):
            raise ChannelError(
                "LinkedIn: кнопка «Отправить» так и не стала активной — "
                "сообщение не отправлено (не догрузилось вложение?)")
        _click_via_dom(target)
    else:
        page.keyboard.press("Enter")

    if not _wait_until(page, lambda: not (composer.inner_text() or "").strip(),
                       _SEND_CONFIRM_TIMEOUT_MS):
        raise ChannelError(
            "LinkedIn: текст остался в поле ввода — отправка не подтверждена")


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
    composer = box.last
    # focus(), not click(): the click is only here to put the caret in the box,
    # and a hit-point click carries the same viewport dependency that killed the
    # send (see _press_send). Measured live on a minimised bubble — click() times
    # out, focus() and fill() both work, because neither needs a hit point.
    composer.focus()
    composer.fill(content.body)
    if content.attachment_path:
        _attach_cv(page, content.attachment_path)
    _press_send(page, composer)


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
            raise _NoteQuotaSpent()
        raise ChannelError("LinkedIn: поле записки не найдено")
    box.first.fill(note[:_NOTE_LIMIT])
    page.wait_for_timeout(500)
    page.locator(SEL_INVITE_SEND).first.click()
    page.wait_for_timeout(1500)


class _NoteQuotaSpent(Exception):
    """Internal: the monthly personalized-invite quota is gone, so the note field
    never appeared. The caller sends the request without a note instead."""


def send_invite_without_note(page) -> None:
    """With the invite modal open, send the request as-is — no note.

    Used only once the personalized quota is spent. The request still reaches the
    person; the cover letter does not, which is why the lead is recorded as
    `invited` rather than sent, and why a later run messages them for real.
    """
    plain = page.locator(SEL_INVITE_SEND_PLAIN)
    target = plain if plain.count() > 0 else page.locator(SEL_INVITE_SEND)
    if target.count() == 0:
        raise ChannelError("LinkedIn: в модалке приглашения нет кнопки отправки")
    target.first.click()
    page.wait_for_timeout(1500)


def read_invite_state(page, profile_url: str) -> str:
    """Where an already-sent invite stands: pending | accepted | gone.

    `pending` — still unanswered (the action bar offers to withdraw it), and also
    the answer whenever the page cannot be read as a profile at all. `accepted` —
    no pending marker, no Connect action, and a real message affordance on the
    card. `gone` — a Connect action is back, so the invite was declined, withdrawn
    or expired.

    "accepted" is a POSITIVE finding, never a fallback. It was one at first, and
    that cost four leads: `_followup_invited` handed it a lead whose target is a
    POST url, the post page has no top card, no pending marker and no Connect —
    so it fell through to "accepted", the run tried to message people who had not
    accepted anything, and each one turned into `failed` (leads 141/143/144/145,
    2026-07-29). Anything we cannot read now answers `pending`, which costs one
    re-check next run and nothing else.
    """
    page.goto(profile_url, wait_until="domcontentloaded")
    _settle(page)
    if page.locator(SEL_INVITE_PENDING).count() > 0:
        return "pending"
    if _topcard_connect(page) is not None:
        return "gone"
    if page.locator(SEL_MORE_BTN).count() > 0 and _open_more_menu(page):
        page.keyboard.press("Escape")      # leave the menu off the message button
        return "gone"
    if page.locator(SEL_COMPOSE).count() == 0:
        return "pending"                   # not a profile card we can read
    return "accepted"


def connect_with_note(page, note: str) -> None:
    """On an already-open profile, send a connection request with a note. Reaches
    Connect via the top card or the "…"/Еще menu. Raises if no Connect action
    exists or the note modal can't be reached."""
    if not _open_invite_modal(page):
        raise ChannelError("LinkedIn: действие «Установить контакт» не найдено на профиле")
    _fill_invite_note(page, note)


def message_or_connect(page, profile_url: str, content: OutreachContent,
                       allow_note: bool = True) -> None:
    """Reach out to a profile. Prefer a connection request with a note whenever a
    Connect action exists — a non-contact can only be *messaged* via paid InMail,
    but a free invite carries the same cover letter. That invite IS the whole
    outreach (signalled via InvitePendingError): no CV rides an invite and we do
    not chase a CV afterwards — it lands out of context. Only a 1st-degree contact
    (no Connect action anywhere) is messaged directly, and there the CV is sent."""
    page.goto(profile_url, wait_until="domcontentloaded")
    _settle(page)
    if _open_invite_modal(page):
        if not allow_note:
            # The quota was already found spent earlier in this run; skip straight
            # to the plain request instead of re-opening the upsell every lead.
            send_invite_without_note(page)
            raise InviteWithoutNoteError(
                f"LinkedIn: запрос на контакт отправлен БЕЗ письма (лимит "
                f"персональных приглашений исчерпан): {profile_url}")
        try:
            _fill_invite_note(page, content.body)
        except _NoteQuotaSpent:
            # The note field never appeared — a Premium upsell took its place. The
            # modal is now in the upsell state, so close it and open a fresh one
            # rather than guessing which of its buttons still sends.
            page.keyboard.press("Escape")
            page.wait_for_timeout(800)
            if not _open_invite_modal(page):
                raise ChannelError(
                    "LinkedIn: не смог переоткрыть модалку приглашения после "
                    "упора в лимит записок")
            send_invite_without_note(page)
            raise InviteWithoutNoteError(
                f"LinkedIn: запрос на контакт отправлен БЕЗ письма (лимит "
                f"персональных приглашений исчерпан): {profile_url}")
        raise InvitePendingError(
            f"LinkedIn: отправлен запрос на контакт с сопроводительным письмом: {profile_url}")
    if page.locator(SEL_MESSAGE_BTN).count() > 0:
        _send_message(page, content)
        return
    raise ChannelError(f"LinkedIn: ни «Сообщение», ни «Контакт» не найдены на {profile_url}")


# The job id inside a LinkedIn job URL. Two shapes are in the wild and only one
# of them used to parse:
#   /jobs/view/4425082337/
#   /jobs/view/staff-backend-software-engineer-at-enhesa-4425082337/   <- share form
# The old pattern demanded digits directly after `/jobs/view/`, so the share form
# answered "" — and an empty id disables three things at once: `_open_apply_flow`
# can no longer tell whether an entry point belongs to THIS job, the Voyager
# lookup below bails before it starts, and `_still_on_the_job` waves the walk
# through. Lead #169 was an ordinary Easy Apply vacancy that came out of all that
# as «нет ссылки внешнего отклика» (2026-07-30, measured live: the entry point was
# on the page and its href carried the id).
#
# The id is the run of digits that ENDS the path segment, and the trailing anchor
# is what says so: a slug carries digits of its own («python-3-developer»), and
# without the anchor the lazy prefix stops at the first of them and returns "3".
_JOB_ID_PATTERN = r"/jobs/view/(?:[^/?#]*?-)?(\d+)(?:[/?#]|$)"
_JOB_ID_RE = re.compile(_JOB_ID_PATTERN)

# LinkedIn's Voyager API holds an offsite job's real apply target as
# `companyApplyUrl`. We read it directly (an in-page fetch carries the logged-in
# session + csrf) instead of clicking the "apply on the company site" button,
# which — like the now-removed jobs-apply-button class — does NOT navigate under
# browser automation.
#
# The id pattern is injected rather than written out again: this file already
# carried two copies of it, and both were wrong in the same way for share URLs.
_VOYAGER_APPLY_JS = r"""
async (jobUrl) => {
  const m = (jobUrl || location.pathname).match(new RegExp(__JOB_ID_PATTERN__));
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
""".replace("__JOB_ID_PATTERN__", json.dumps(_JOB_ID_PATTERN))


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


def _open_apply_flow(page, job_url: str):
    """Navigate into a job's Easy Apply flow. Raises _ExternalApplyNeeded if none.

    Entered by NAVIGATING to the anchor's href, not by clicking it. Measured live
    (2026-07-29): a native el.click() on the entry point leaves the page exactly
    where it was — no dialog, no new tab, no URL change, 15s of polling — the same
    behaviour this file already documents for the "apply on the company site"
    button. The anchor carries the destination
    (`/jobs/view/<id>/apply/?openSDUIApplyFlow=true&trackingId=…`), so reading the
    href and going there directly sidesteps the SPA entirely, exactly as
    `fetch_company_apply_url` does for external applies. The click is kept as a
    fallback for a rendering that has no href.

    The entry point must belong to THIS job. Matching on the caption alone is not
    enough: the "similar jobs" rail badges other people's vacancies with the very
    same words, so a job with no Easy Apply of its own still produced matches —
    7 of them for lead 123, 4 for lead 129, every one an <a> pointing at
    `/jobs/search-results/?keywords=…` with an empty aria-label (measured live
    2026-07-29). Following one of those left the browser paging through somebody
    else's search results, and it also robbed both leads of the external apply
    they should have had. So an entry counts only when its href carries this
    job's id; when none does, this is not an Easy Apply job.
    """
    page.goto(job_url, wait_until="domcontentloaded")
    _settle(page)                    # the top card mounts client-side, after DCL
    entry = page.locator(SEL_EASY_APPLY)
    count = entry.count()
    if count == 0:
        raise _ExternalApplyNeeded()

    job_id = _job_id(job_url)
    hrefless = None
    for i in range(min(count, 12)):
        candidate = entry.nth(i)
        try:
            href = candidate.get_attribute("href") or ""
        except Exception:  # noqa: BLE001 — a re-render can detach a handle
            continue
        if href and job_id and job_id in href:
            page.goto(href, wait_until="domcontentloaded")
            _settle(page)
            return candidate
        if not href and hrefless is None:
            hrefless = candidate

    # No href names this job. A single caption-only control is still plausibly the
    # real button (an older rendering); several are the rail, and guessing among
    # them is how the walk ended up in another vacancy.
    if hrefless is not None and count == 1:
        _click_via_dom(hrefless)
        _settle(page)
        return hrefless
    raise _ExternalApplyNeeded()
    return entry


def _job_id(url: str) -> str:
    """The numeric job id, from either URL shape (see _JOB_ID_PATTERN)."""
    m = _JOB_ID_RE.search(url or "")
    return m.group(1) if m else ""


def _still_on_the_job(page, job_id: str) -> bool:
    """Is the browser still on the job we started applying to?

    The walk clicks a button called «Далее», and the job page has more than one:
    the similar-jobs rail paginates with the same caption. When the apply flow
    is not open, the walk paged through search results instead — observed
    2026-07-29, leads 118/119/123/129 all ended on
    `/jobs/search-results/?currentJobId=<a different job>&start=200`, eight
    clicks deep into somebody else's vacancy. Nothing was submitted there, but
    only because no submit button turned up; that is luck, not a guarantee.
    """
    if not job_id:
        return True
    try:
        return job_id in (page.url or "")
    except Exception:  # noqa: BLE001
        return True


def _first_alert_text(page, limit: int = 6) -> str:
    """Text of the first non-empty alert on the page, or "" when there is none."""
    alerts = page.locator(SEL_APPLY_ALERT)
    try:
        n = min(alerts.count(), limit)
    except Exception:  # noqa: BLE001
        return ""
    for i in range(n):
        try:
            said = (alerts.nth(i).inner_text(timeout=1500) or "").strip()
        except Exception:  # noqa: BLE001 — a live region may vanish mid-read
            continue
        if said:
            return said[:120]
    return ""


def easy_apply_via_page(page, job_url: str, content: OutreachContent,
                        profile=None, cv_path: str = "", answerer=None,
                        dry_run: bool = False) -> None:
    """Open a job and apply through Easy Apply, walking its multi-step flow.

    Raises _ExternalApplyNeeded when the job has no Easy Apply at all — the
    channel then falls back to the company's own site.

    The walk fills each screen from the apply profile and advances, and submits
    only when the submit button appears. The invariant that makes that safe is the
    same one the external-apply path uses: a screen whose REQUIRED fields cannot
    all be filled stops the walk with ManualApplyRequired rather than advancing.
    A half-filled application is worse than no application, and this page submits
    to a real employer.

    ManualApplyRequired, not ChannelError, throughout: an Easy Apply we can't drive
    is a lead for a human to finish, which is `manual`. The old code raised
    ChannelError here, and the send loop writes `failed` for that — a terminal
    status that reads like the send broke, on a lead nothing was ever wrong with.
    """
    from app.infrastructure.channels.external_apply import (
        fill_fields, scrape_until_ready,
    )
    from app.application.auto_apply import answer_ai_fields, build_plan

    job_id = _job_id(job_url)
    _open_apply_flow(page, job_url)

    for step in range(_APPLY_MAX_STEPS):
        submit = page.locator(SEL_APPLY_SUBMIT)
        if submit.count() > 0:
            if dry_run:
                raise ManualApplyRequired(
                    f"DRY_RUN: дошёл до отправки за {step} шаг(ов), НЕ отправлено: {job_url}")
            _click_via_dom(submit.first)
            return

        if profile is not None:
            # Only scrape when there is something to fill with. LinkedIn prefills
            # the contact step from the account itself, so a run without an apply
            # profile can still walk the flow — it just adds nothing of its own.
            obs, _route = scrape_until_ready(page)
            plan = build_plan(obs, profile, cv_path)
            answer_ai_fields(plan, answerer, content.body)
            missing = plan.unmapped_required()
            if missing:
                raise ManualApplyRequired(
                    f"LinkedIn Easy Apply, шаг {step + 1}: не заполнены обязательные "
                    f"поля {missing} — дожми вручную: {job_url}")
            fill_fields(page, plan, where="LinkedIn Easy Apply")
            # The resume step uploads a file; the screen only accepts "Проверить"
            # once that POST has landed. Settling here is the difference between
            # advancing and bouncing off a validation message.
            _settle(page)

        nxt = page.locator(SEL_APPLY_NEXT)
        if nxt.count() == 0:
            raise ManualApplyRequired(
                f"LinkedIn Easy Apply: на шаге {step + 1} нет ни отправки, ни «Далее» "
                f"— дожми вручную: {job_url}")
        # Native el.click(), matching every other LinkedIn control this file drives.
        _click_via_dom(nxt.first)
        _settle(page)

        # Did that click stay inside the application? «Далее» is also the caption
        # on the similar-jobs rail, so a click landing on the job page instead of
        # the flow walks off into other people's vacancies. Checked immediately,
        # because the next iteration would look for a SUBMIT button on whatever
        # page it ended up on. The link handed to the human is `job_url`, never
        # `page.url` — by this point `page.url` is exactly the wrong place.
        if not _still_on_the_job(page, job_id):
            raise ManualApplyRequired(
                f"LinkedIn Easy Apply: форма закрылась на шаге {step + 1} "
                f"(браузер ушёл со страницы вакансии) — дожми вручную: {job_url}")

        # A validation message means the screen refused to advance, and the walk
        # would otherwise press the same button until the step cap and report the
        # useless "не дошёл за 8 шагов". LinkedIn says exactly what is wrong
        # ("A resume is required"); pass that on instead.
        # Only an alert that actually SAYS something counts. LinkedIn keeps empty
        # `role=alert` live regions on the page for screen readers, and treating
        # their mere presence as a failure stopped the walk on step 1 with
        # "проверка не пройдена" and nothing to act on.
        said = _first_alert_text(page)
        if said:
            raise ManualApplyRequired(
                f"LinkedIn Easy Apply, шаг {step + 1}: форма не приняла — "
                f"{said} — дожми вручную: {job_url}")

    raise ManualApplyRequired(
        f"LinkedIn Easy Apply: не дошёл до отправки за {_APPLY_MAX_STEPS} шагов "
        f"— дожми вручную: {job_url}")


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
        # Set once the personalized-invite quota is found spent, so the rest of the
        # run skips straight to note-less requests instead of re-opening the
        # Premium upsell for every remaining lead.
        self._note_quota_spent = False

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
                # The same profile/CV/answerer the external path uses: an Easy
                # Apply screen asks for the same facts a company's own form does,
                # and answering them from two different sources would drift.
                easy_apply_via_page(
                    self._page, target, content,
                    profile=self._ext.get("profile"),
                    cv_path=self._ext.get("cv_path", ""),
                    answerer=self._ext.get("answerer"),
                    dry_run=self._ext.get("dry_run", False))
            except _ExternalApplyNeeded:
                self._external_apply(target, content)
            return
        if action == "post":
            # A hiring post: message its author (id is embedded in the post URL).
            author = post_author_profile_url(target)
            if not author:
                raise ChannelError(f"LinkedIn пост: не удалось определить автора: {target}")
            target = author
        try:
            message_or_connect(self._page, target, content,
                               allow_note=not self._note_quota_spent)
        except InviteWithoutNoteError:
            self._note_quota_spent = True
            raise

    def invite_state(self, target: str) -> str:
        """pending | accepted | gone for a profile we already invited.

        Resolves a post url to its author first, exactly as `send` does — an
        `invited` lead very often points at the hiring post, not at the person.
        """
        if self._page is None:
            raise ChannelError("LinkedInChannel.start() not called")
        target = target.strip()
        if linkedin_action_for_url(target) == "post":
            author = post_author_profile_url(target)
            if not author:
                raise ChannelError(
                    f"LinkedIn пост: не удалось определить автора: {target}")
            target = author
        return read_invite_state(self._page, target)

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
