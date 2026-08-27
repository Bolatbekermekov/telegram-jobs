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

# hh.ru data-qa hooks. Verified live 2026-07-08 on a real vacancy detail page;
# fix HERE when they drift. `:visible` on the apply link avoids a hidden
# duplicate (y=0) that would hang the click waiting to become actionable.
# The saved session belongs to hh.ru, and cookies don't cross to hh.kz / hh.uz —
# opening a regional link would browse anonymously and hit the login wall on Apply.
# Vacancy ids are shared network-wide, so the same id on hh.ru resolves to the same
# vacancy, logged in (verified live on vacancy/135297431: hh.kz anonymous, hh.ru not).
_HH_REGIONAL_RE = re.compile(
    r"^https?://(?:[\w.-]*\.)?hh\.(?:kz|uz|by|kg|az|tj)/", re.IGNORECASE)


def to_session_domain(url: str) -> str:
    """Rewrite a regional HeadHunter link onto hh.ru, where our session lives."""
    return _HH_REGIONAL_RE.sub("https://hh.ru/", url, count=1)


SEL_APPLY = "[data-qa='vacancy-response-link-top']:visible"
SEL_ALREADY_APPLIED = "[data-qa='vacancy-response-link-view-topic']"
# Consent popups shown when applying to a vacancy in another country (the account
# is in KZ, the vacancies are RU). TWO different ones appear:
#  * the profile-visibility popup (older), and
#  * the "You are applying from another country / Still apply" relocation warning
#    (data-qa relocation-warning-*), which BLOCKS the response form until its
#    "Still apply" is clicked — an unhandled block reported as "поле письма не
#    появилось" (seen live 2026-07-22 on RU gamedev vacancies).
# Both confirm buttons are clicked when present.
SEL_COUNTRY_CONFIRM = ("[data-qa='countries-profile-visibility-popup-confirm'], "
                       "[data-qa='relocation-warning-confirm']")
SEL_LETTER_TOGGLE = "[data-qa='vacancy-response-letter-toggle']"
SEL_LETTER_INPUT = "[data-qa='vacancy-response-popup-form-letter-input']"
SEL_SUBMIT = "[data-qa='vacancy-response-submit-popup']"
# Default wait for that Submit button; the channel passes HH_SUBMIT_TIMEOUT_SECONDS.
SUBMIT_TIMEOUT_MS = 100_000
# Employer screening questions: free-text <textarea name="task_<id>_text"> and
# single-choice radio groups <input type=radio name="task_<id>">. Mandatory, so
# without an AI answerer we skip; with one we answer and submit (see below).
SEL_QUESTIONS = "textarea[name^='task_'], input[type=radio][name^='task_']"
SEL_DESCRIPTION = "[data-qa='vacancy-description']"
_LOGIN_MARKERS = ("/account/login", "/login", "captcha")

# --- CV + cover letter in the vacancy chat ---------------------------------
# hh keeps your online resume ON the response; the response form has no PDF
# upload. But the vacancy CHAT (a separate app, "chatik") sends both a message
# and a file. Verified live 2026-07-09 (chat/5464684008): the response page has
# `open-vacancy-chat`, which opens chatik in an IFRAME; its `open-in-new-tab`
# button gives a standalone chat page (hh.ru/chat/<id>) whose composer is
# top-level and easy to drive. We attach the PDF via chatik's pre-rendered
# hidden <input data-qa=upload-file-input> (accepts pdf) with set_input_files —
# no "+" click, so no native OS picker can hang the run. The send button has a
# disabled duplicate (global widget), so we click only the ENABLED one.
# Entry point into the employer chat, after a response has been sent. hh now
# renders it as `vacancy-response-link-view-topic` (a button labelled "Chat" /
# "Перейти в чат") — the same data-qa that marks an already-applied vacancy, which
# is consistent: the element only exists once a response exists. `open-vacancy-chat`
# is kept first because it is still the one some flows render.
SEL_CHAT_OPEN_BTN = ("[data-qa='open-vacancy-chat']:visible, "
                     "[data-qa='vacancy-response-link-view-topic']:visible")
SEL_CHAT_NEWTAB_BTN = "[data-qa='chatik-open-in-new-tab-button']"
# Поле сообщения в чате. ДВА имени, и это не перестраховка: замер 2026-08-27
# (снимок .hh_chat_debug/hh_chat_no_message_box.html) показал, что hh переехал на
# дизайн-систему magritte и прежнее имя `chatik-new-message-text` в разметке
# исчезло — 0 совпадений, — а поле стало родовым `text-input` внутри контейнера
# `chatik-message-input`. Композер при этом раскрывался нормально: письмо
# терялось ровно на опознании поля, и работодатели получали голый отклик.
#
# Одного `text-input` мало: такое имя носит любой текстовый ввод страницы,
# включая поиск в шапке, а письмо, напечатанное в строку поиска, не дойдёт
# никому и в логе не отзовётся. Поэтому обязателен контейнер чата.
#
# Старое имя оставлено первым: hh раскатывает интерфейс не всем сразу.
SEL_CHAT_MSG = ("textarea[data-qa='chatik-new-message-text']:visible, "
                "[data-qa='chatik-message-input'] textarea[data-qa='text-input']:visible")
SEL_CHAT_FILE_INPUT = "input[data-qa='upload-file-input']"
SEL_CHAT_SEND_ENABLED = "button[data-qa='chatik-do-send-message']:not([disabled])"
# Чат вакансии по своей воле НЕ открывается: на странице отклика, где переписка
# ещё не завязалась, поля сообщения нет вовсе, а внизу написано «Chat will be
# available after the employer sends you an invitation» (замер 2026-08-24,
# hh.ru/chat/5569971942 против 5569995463, где переписка идёт и поле есть).
#
# Зато hh предлагает штатный путь: «Add a cover letter» — приложить письмо к уже
# поданному отклику. По клику появляются и поле сообщения (тот же
# `chatik-new-message-text`), и поле файла, и кнопка отправки. Для вакансий с
# откликом в один клик это ЕДИНСТВЕННЫЙ способ доставить письмо и резюме.
SEL_CHAT_ADD_LETTER = "a[data-qa='chatik-chat-message-applicant-action']"


def collect_questions(page) -> list:
    """Scrape hh employer questions into [{id, type, prompt, options}].

    Fragile by nature (hh puts no data-qa on questions): the prompt is the
    nearest text above each control. Isolated here so drift is easy to fix.
    """
    return page.evaluate(r"""() => {
      const promptFor = (el) => {
        let node = el;
        for (let i = 0; i < 7 && node; i++) {
          let sib = node.previousElementSibling;
          while (sib) {
            const t = (sib.innerText || '').trim();
            if (t && t !== 'Писать тут' && t.length > 6)
              return t.split('\n')[0].slice(0, 240);
            sib = sib.previousElementSibling;
          }
          node = node.parentElement;
        }
        return '';
      };
      const out = [], seen = new Set();
      document.querySelectorAll(
        "textarea[name^='task_'], input[type=radio][name^='task_']").forEach(el => {
        let id, type, options = [];
        if (el.tagName === 'TEXTAREA') { id = el.name.replace(/_text$/, ''); type = 'text'; }
        else {
          id = el.name; type = 'choice';
          options = Array.from(document.querySelectorAll("input[name='" + id + "']"))
            .map(r => ((r.closest('label') || r.parentElement || {}).innerText || '').trim());
        }
        if (seen.has(id)) return;
        seen.add(id);
        out.push({ id, type, prompt: promptFor(el), options });
      });
      return out;
    }""")


def _click_choice(page, qid: str, index: int) -> None:
    """Select radio option `index` of group `qid`. hh hides the native input,
    so prefer clicking its wrapping label; fall back to checking the input."""
    label = page.locator(f"label:has(input[name='{qid}'])")
    if label.count() > index:
        label.nth(index).click()
    else:
        page.locator(f"input[name='{qid}']").nth(index).check()


def _fill_questions(page, questions, answers_by_id) -> None:
    from app.application.hh_questions import fill_plan

    for kind, qid, value in fill_plan(questions, answers_by_id):
        if kind == "text":
            page.locator(f"textarea[name='{qid}_text']").first.fill(value)
        else:
            _click_choice(page, qid, value)


def _verify_submitted(page) -> None:
    """After submit, the response form closes; if the submit button is still
    there the form was rejected (unanswered/invalid) — fail instead of lying."""
    page.wait_for_timeout(3000)
    if page.locator(SEL_SUBMIT).count() > 0:
        raise ChannelError("hh: отклик не подтверждён (форма не принята)")


def _dump_chat_debug(page, debug_dir, tag) -> None:
    """Save the current DOM + screenshot so unverified chat selectors can be
    finalized from ONE real send instead of live-probing (ban risk). No-op if
    debug_dir is None (tests) or on any I/O error."""
    if not debug_dir:
        return
    from pathlib import Path
    try:
        d = Path(debug_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{tag}.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(d / f"{tag}.png"))
    except Exception:  # noqa: BLE001 — debug capture must never break a send
        pass


def _neutralize_cookie_banner(page) -> None:
    """Disable hh's bottom cookie-policy banner so it can't swallow clicks.

    The banner (`data-qa=cookies-policy-informer`, id `bottom-cookies-policy-informer`)
    is a fixed overlay along the bottom of the page. It sits over the response
    form's letter toggle and the chat composer's message field / send button, so a
    normal click lands on the banner instead — and the cover letter silently never
    reaches the employer (seen live 2026-07-22 on vacancy 134940090 and 135327464,
    where the response went through but the letter click timed out on the banner).
    Killing its pointer events clears the intercept without needing its dismiss
    button; best-effort, since the banner is absent once cookies are accepted."""
    try:
        page.evaluate(
            "() => document.querySelectorAll("
            "\"[data-qa='cookies-policy-informer'], #bottom-cookies-policy-informer\")"
            ".forEach(el => { el.style.pointerEvents = 'none'; el.style.display = 'none'; })")
    except Exception:  # noqa: BLE001 — best-effort; a missing banner is fine
        pass



def _click_via_dom(locator) -> None:
    """Нативный el.click() вместо клика по координатам.

    Клику Playwright нужна точка попадания, и любой элемент поверх кнопки его
    съедает. Именно так пропали 16 сопроводительных писем и 16 резюме подряд
    (замер 2026-08-23/24): кнопка чата была видима, включена и стабильна, а
    клик 30 секунд отваливался о фон модалки. Нативный клик хит-теста не
    делает — тот же приём и по той же причине уже применён в канале LinkedIn.
    """
    locator.evaluate("el => el.click()")


def _neutralize_modal_overlay(page) -> None:
    """Погасить модалку, которую hh показывает СРАЗУ после отклика.

    В логе Playwright она значилась как `<div data-qa="modal-overlay"> intercepts
    pointer events`. Живёт ровно этот момент: на перезагруженной странице той же
    вакансии (136487691, замер 2026-08-24) модалок ноль, а кнопок чата две и они
    видимы — значит гасить её безопасно, кнопка лежит на самой странице, а не
    внутри неё. Кнопки закрытия у модалки нет (`[data-qa*=close]` даёт 0),
    поэтому глушим так же, как баннер кук: точечно, по pointer-events.
    """
    try:
        page.evaluate(
            "() => document.querySelectorAll(\"[data-qa='modal-overlay']\")"
            ".forEach(el => { el.style.pointerEvents = 'none'; el.style.display = 'none'; })")
    except Exception:  # noqa: BLE001 — модалки может не быть, это норма
        pass


def _chat_send(chat) -> None:
    """Send the composed chatik message. A disabled duplicate of the send button
    exists (global chat widget), so click only the enabled one; fall back to
    Enter (chatik: Enter = send)."""
    btn = chat.locator(SEL_CHAT_SEND_ENABLED)
    if btn.count() > 0:
        # Нативный клик: превью приложенного файла и подсказки чата перекрывают
        # кнопку, и клик по координатам отваливался по таймауту (замер
        # 2026-08-24, чат 5569971942).
        _click_via_dom(btn.first)
    else:
        chat.locator(SEL_CHAT_MSG).first.press("Enter")


def attach_cv_via_chat(page, attachment_path: str | None = None, debug_dir=None,
                       letter=None) -> None:
    """In the vacancy chat, send the cover `letter` (if given) and the CV PDF,
    AFTER a successful response.

    Opens chatik via `open-vacancy-chat` and, when available, its
    `open-in-new-tab` button (a standalone chat page is far easier to drive).
    Best-effort and self-diagnosing: raises ChannelError (with a DOM dump) if
    the chat or its file input can't be found — the caller treats that as a
    warning, since the application itself already went through."""
    _neutralize_cookie_banner(page)
    _neutralize_modal_overlay(page)
    opener = page.locator(SEL_CHAT_OPEN_BTN)
    if opener.count() == 0:
        _dump_chat_debug(page, debug_dir, "hh_chat_no_open_button")
        raise ChannelError("кнопка чата (open-vacancy-chat) не найдена")
    _click_via_dom(opener.first)
    page.wait_for_timeout(4000)

    # Prefer the standalone chat tab (top-level composer, no iframe).
    chat = page
    newtab = page.locator(SEL_CHAT_NEWTAB_BTN)
    if newtab.count() > 0:
        try:
            with page.context.expect_page(timeout=10000) as pop:
                # Тоже нативным кликом: модалка отклика перекрывает и эту
                # кнопку, а отдельная вкладка чата — единственный путь, где
                # композер лежит на верхнем уровне. В самой странице он живёт
                # внутри iframe, и `page.locator` его не видит (замер
                # 2026-08-24: 11 фреймов, 9 chatik-элементов, textarea — во
                # фрейме; во вкладке hh.ru/chat/<id> поле находится сразу).
                _click_via_dom(newtab.first)
            chat = pop.value
            chat.wait_for_timeout(6000)
        except Exception:  # noqa: BLE001 — fall back to the in-page chat panel
            chat.wait_for_timeout(2000)

    # The chat (in-page panel or new tab) carries the same cookie banner over its
    # composer — clear it there too, or the message-field click below is swallowed.
    _neutralize_cookie_banner(chat)

    # 1) Cover letter as a chat message — only when it wasn't already sent via
    #    the response form (e.g. one-click-apply vacancies pass it here).
    revealed = False
    if letter:
        box = chat.locator(SEL_CHAT_MSG)
        if box.count() == 0:
            # Поля нет — значит переписка ещё не открыта. Просим hh раскрыть
            # композер штатной ссылкой «Add a cover letter»: она есть ровно
            # тогда, когда к отклику письма ещё не приложено.
            add = chat.locator(SEL_CHAT_ADD_LETTER)
            if add.count() > 0:
                _click_via_dom(add.first)
                chat.wait_for_timeout(3000)
                box = chat.locator(SEL_CHAT_MSG)
                revealed = True
        if box.count() == 0:
            # Раньше здесь стояло `if box.count() > 0`, и отсутствие поля молча
            # пропускало письмо: отклик засчитывался успешным, а работодателю не
            # уходило ни строчки. Молчаливая потеря письма — худший исход, чем
            # громкая: она не видна ни в таблице, ни в логе.
            _dump_chat_debug(chat, debug_dir, "hh_chat_no_message_box")
            raise ChannelError("поле сообщения в чате не найдено — письмо не отправлено")
        # Виджет «Add a cover letter» ОДНОРАЗОВЫЙ: после отправки он исчезает
        # вместе с полем файла, и второго захода не будет. Поэтому в раскрытом
        # композере резюме прикладывается ДО текста, и всё уходит одной
        # отправкой. Порядок проверен живьём 2026-08-24: после файла и текста
        # кнопка отправки становится активной.
        if revealed and attachment_path:
            revealed_file = chat.locator(SEL_CHAT_FILE_INPUT)
            if revealed_file.count() == 0:
                _dump_chat_debug(chat, debug_dir, "hh_chat_no_file_input")
                raise ChannelError("поле файла (upload-file-input) в чате не найдено")
            revealed_file.last.set_input_files(attachment_path)
            chat.wait_for_timeout(2500)
            attachment_path = None      # уже приложено, второй раз не нужно
        # Без предварительного клика: `fill()` сам ставит фокус, а клику нужна
        # точка попадания — и её съедает превью только что приложенного файла
        # (замер 2026-08-24: click по textarea отваливался 30 с, тогда как
        # fill на том же поле срабатывал сразу). Тот же урок, что в LinkedIn.
        box.first.fill(letter)
        chat.wait_for_timeout(800)
        _chat_send(chat)
        chat.wait_for_timeout(2500)

    # 2) The CV PDF via chatik's pre-rendered hidden file input (accepts pdf) —
    #    no "+" click, so no native OS picker can hang the run. Optional: with the
    #    PDF turned off the letter above is still the delivery that mattered.
    if not attachment_path:
        return
    file_input = chat.locator(SEL_CHAT_FILE_INPUT)
    if file_input.count() == 0:
        _dump_chat_debug(chat, debug_dir, "hh_chat_no_file_input")
        raise ChannelError("поле файла (upload-file-input) в чате не найдено")
    file_input.last.set_input_files(attachment_path)
    chat.wait_for_timeout(2500)
    _chat_send(chat)
    chat.wait_for_timeout(2500)


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


_APPLIED_MARKERS = ("Вы откликнулись", "Вы уже откликались", "You applied",
                    "You have already applied")


def _already_applied(page) -> bool:
    """True if the page shows an applied confirmation — the 'view topic' link or
    the applied text (RU/EN). Detects one-click-apply vacancies that submit on
    the apply click itself, with no letter form."""
    if page.locator(SEL_ALREADY_APPLIED).count() > 0:
        return True
    try:
        body = page.inner_text("body")
    except Exception:  # noqa: BLE001
        return False
    return any(m in body for m in _APPLIED_MARKERS)


def _maybe_attach_cv(page, content, attach_cv_in_chat, debug_dir, letter=None) -> None:
    """Deliver the cover `letter` and/or the CV PDF through the vacancy chat.

    The letter is the point of this tool, so it is NOT gated on the CV setting:
    hh's quick-apply vacancies send the response on the apply click with no letter
    form at all, and the chat is then the only way it reaches the employer. Gating
    both on `attach_cv_in_chat` meant turning off the PDF silently dropped the
    letter too.

    Never fails the (already sent) application — but says plainly which part
    didn't make it, since a delivered application with no letter is the failure
    mode that matters here.
    """
    want_cv = bool(attach_cv_in_chat and content.attachment_path)
    if not (letter or want_cv):
        return
    try:
        attach_cv_via_chat(page, content.attachment_path if want_cv else None,
                           debug_dir, letter)
    except Exception as exc:  # noqa: BLE001 — response already succeeded
        if letter:
            print(f"⚠️  hh: ОТКЛИК ОТПРАВЛЕН, НО СОПРОВОДИТЕЛЬНОЕ ПИСЬМО НЕ ДОШЛО ({exc}). "
                  "Текст письма — в колонке «Сообщение», отправь его в чате вручную.")
        else:
            print(f"⚠️  hh: отклик отправлен, CV в чат не приложен: {exc}")


def apply_via_page(page, url: str, content: OutreachContent, answerer=None,
                   attach_cv_in_chat: bool = False, debug_dir=None,
                   submit_timeout_ms: int = SUBMIT_TIMEOUT_MS) -> None:
    url = to_session_domain(url)
    resp = page.goto(url, wait_until="domcontentloaded")
    _check_not_blocked(page)
    # hh answers 403 for a vacancy that is archived or restricted to certain users.
    # Without this the run falls through to the missing Apply button and reports
    # "no apply button", which reads like a broken selector rather than a dead link.
    if resp is not None and resp.status >= 400:
        raise ChannelError(f"вакансия недоступна (HTTP {resp.status}): {url}")
    if page.locator(SEL_ALREADY_APPLIED).count() > 0:
        raise ChannelError(f"already applied: {url}")
    # Grab the vacancy text now (for answering questions) before we leave the page.
    vacancy_context = ""
    if answerer is not None:
        try:
            vacancy_context = page.locator(SEL_DESCRIPTION).first.inner_text(timeout=5000)[:6000]
        except Exception:  # noqa: BLE001 — answering still works without it
            vacancy_context = ""
    apply_btn = page.locator(SEL_APPLY)
    if apply_btn.count() == 0:
        raise ChannelError(
            f"нет кнопки отклика (вакансия закрыта или доступна не всем): {url}")
    apply_btn.first.click()
    _check_not_blocked(page)
    # After the click hh may show a country-visibility consent popup (foreign
    # vacancy) and/or render the inline response form. Wait for any of them,
    # best-effort — the optional checks below still run if the wait times out.
    try:
        page.wait_for_selector(
            f"{SEL_COUNTRY_CONFIRM}, {SEL_LETTER_TOGGLE}, {SEL_LETTER_INPUT}, "
            f"{SEL_ALREADY_APPLIED}", timeout=15000)
    except Exception:  # noqa: BLE001
        pass
    # Clear the cookie banner before any click below: it overlays the letter
    # toggle, so an intercepted toggle click leaves the letter field unexpanded
    # and the run reports "поле письма не появилось".
    _neutralize_cookie_banner(page)
    # Consent popup for a vacancy in another country — optional. The relocation
    # warning BLOCKS the response form, so after confirming, wait for it to close
    # and the form (or the submitted-response chat) to render before going on.
    if page.locator(SEL_COUNTRY_CONFIRM).count() > 0:
        page.locator(SEL_COUNTRY_CONFIRM).first.click()
        page.wait_for_timeout(2500)
    # The cover-letter field may need expanding first — also optional.
    if page.locator(SEL_LETTER_TOGGLE).count() > 0:
        page.locator(SEL_LETTER_TOGGLE).first.click()
    # Mandatory employer questions: answer them with the AI, or skip if there's
    # no answerer wired in (so we never send a half-filled application).
    if page.locator(SEL_QUESTIONS).count() > 0:
        if answerer is None:
            raise ChannelError(
                f"вакансия с обязательными вопросами работодателя, нужен ручной отклик: {url}")
        questions = collect_questions(page)
        _fill_questions(page, questions, answerer(questions, vacancy_context))
    # Ask "did the response already go through?" BEFORE touching the letter form.
    # hh's quick apply submits on the apply click itself and only then offers an
    # optional cover-letter popup, whose submit control is NOT
    # `vacancy-response-submit-popup`. Checking the form first meant we filled that
    # popup, waited 30s for a button it never had, and reported `failed` for an
    # application that was in fact sent (live: vacancy/135269482 and /135056818).
    if _already_applied(page):
        print(f"ℹ️  hh: отклик подан в один клик (онлайн-резюме); письмо и CV — в чат: {url}")
        # No letter reached the employer with the response, so send it in the chat.
        _maybe_attach_cv(page, content, attach_cv_in_chat, debug_dir, letter=content.body)
        return
    if page.locator(SEL_LETTER_INPUT).count() == 0:
        _dump_chat_debug(page, debug_dir, "hh_no_letter_field")
        raise ChannelError(
            f"hh: поле письма не появилось и отклик не подтверждён — проверь вручную: {url}")
    page.locator(SEL_LETTER_INPUT).first.fill(content.body)
    try:
        # Only reached when the response has NOT already gone through — quick-apply
        # is caught above — so this waits on a popup that really is expected to
        # render. Generous by default; tune with HH_SUBMIT_TIMEOUT_SECONDS.
        page.locator(SEL_SUBMIT).first.click(timeout=submit_timeout_ms)
    except Exception as exc:  # noqa: BLE001
        # The click may have failed because the response was already in flight.
        if _already_applied(page):
            print(f"ℹ️  hh: отклик уже отправлен, письмо и CV — в чат: {url}")
            _maybe_attach_cv(page, content, attach_cv_in_chat, debug_dir, letter=content.body)
            return
        _dump_chat_debug(page, debug_dir, "hh_no_submit_button")
        raise ChannelError(
            f"кнопка отправки отклика не найдена ({exc.__class__.__name__}) — "
            f"проверь вручную: {url}") from exc
    _verify_submitted(page)
    # The application is now sent (online resume included). Optionally attach the
    # PDF as an extra in the chat — never letting its failure fail the application.
    _maybe_attach_cv(page, content, attach_cv_in_chat, debug_dir)


class HeadHunterChannel:
    name = "hh"
    body_limit = 10000          # hh.ru cover-letter length limit
    needs_subject = False

    def __init__(self, storage_state_path: str, headless: bool = False, answerer=None,
                 attach_cv_in_chat: bool = False,
                 submit_timeout_ms: int = SUBMIT_TIMEOUT_MS):
        # answerer(questions, vacancy_context) -> {question_id: {"text"|"choice"}}.
        # None => vacancies with mandatory questions are skipped, not answered.
        # attach_cv_in_chat => after responding, also attach the CV PDF in the chat.
        self._storage_state_path = storage_state_path
        self._headless = headless
        self._answerer = answerer
        self._attach_cv_in_chat = attach_cv_in_chat
        self._submit_timeout_ms = submit_timeout_ms
        self._pw = None
        self._browser = None
        self._page = None

    @property
    def _debug_dir(self) -> str:
        from pathlib import Path
        return str(Path(self._storage_state_path).parent / ".hh_chat_debug")

    def start(self) -> None:
        from pathlib import Path

        # No interactive login fallback: hh.ru's anti-fraud blocks the login
        # request (SMS send) in any browser we launch, so the session can only
        # come from `make login_hh` (real Chrome + CDP export).
        if not Path(self._storage_state_path).exists():
            raise ChannelError(
                f"Сессия hh.ru не найдена ({self._storage_state_path}). "
                "Сначала выполни `make login_hh`")

        from patchright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._headless, channel="chrome")
        context = self._browser.new_context(
            storage_state=self._storage_state_path, no_viewport=True)
        self._page = context.new_page()

    def stop(self) -> None:
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def send(self, target: str, content: OutreachContent) -> None:
        if self._page is None:
            raise ChannelError("HeadHunterChannel.start() not called")
        apply_via_page(self._page, vacancy_url(target), content, self._answerer,
                       self._attach_cv_in_chat, self._debug_dir,
                       self._submit_timeout_ms)
