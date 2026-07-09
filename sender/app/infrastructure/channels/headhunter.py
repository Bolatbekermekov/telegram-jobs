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
SEL_APPLY = "[data-qa='vacancy-response-link-top']:visible"
SEL_ALREADY_APPLIED = "[data-qa='vacancy-response-link-view-topic']"
# Consent popup shown when applying to a vacancy in another country (KZ↔RU).
SEL_COUNTRY_CONFIRM = "[data-qa='countries-profile-visibility-popup-confirm']"
SEL_LETTER_TOGGLE = "[data-qa='vacancy-response-letter-toggle']"
SEL_LETTER_INPUT = "[data-qa='vacancy-response-popup-form-letter-input']"
SEL_SUBMIT = "[data-qa='vacancy-response-submit-popup']"
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
SEL_CHAT_OPEN_BTN = "[data-qa='open-vacancy-chat']"
SEL_CHAT_NEWTAB_BTN = "[data-qa='chatik-open-in-new-tab-button']"
SEL_CHAT_MSG = "textarea[data-qa='chatik-new-message-text']:visible"
SEL_CHAT_FILE_INPUT = "input[data-qa='upload-file-input']"
SEL_CHAT_SEND_ENABLED = "button[data-qa='chatik-do-send-message']:not([disabled])"


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


def _chat_send(chat) -> None:
    """Send the composed chatik message. A disabled duplicate of the send button
    exists (global chat widget), so click only the enabled one; fall back to
    Enter (chatik: Enter = send)."""
    btn = chat.locator(SEL_CHAT_SEND_ENABLED)
    if btn.count() > 0:
        btn.first.click()
    else:
        chat.locator(SEL_CHAT_MSG).first.press("Enter")


def attach_cv_via_chat(page, attachment_path: str, debug_dir=None, letter=None) -> None:
    """In the vacancy chat, send the cover `letter` (if given) and the CV PDF,
    AFTER a successful response.

    Opens chatik via `open-vacancy-chat` and, when available, its
    `open-in-new-tab` button (a standalone chat page is far easier to drive).
    Best-effort and self-diagnosing: raises ChannelError (with a DOM dump) if
    the chat or its file input can't be found — the caller treats that as a
    warning, since the application itself already went through."""
    opener = page.locator(SEL_CHAT_OPEN_BTN)
    if opener.count() == 0:
        _dump_chat_debug(page, debug_dir, "hh_chat_no_open_button")
        raise ChannelError("кнопка чата (open-vacancy-chat) не найдена")
    opener.first.click()
    page.wait_for_timeout(4000)

    # Prefer the standalone chat tab (top-level composer, no iframe).
    chat = page
    newtab = page.locator(SEL_CHAT_NEWTAB_BTN)
    if newtab.count() > 0:
        try:
            with page.context.expect_page(timeout=10000) as pop:
                newtab.first.click()
            chat = pop.value
            chat.wait_for_timeout(6000)
        except Exception:  # noqa: BLE001 — fall back to the in-page chat panel
            chat.wait_for_timeout(2000)

    # 1) Cover letter as a chat message — only when it wasn't already sent via
    #    the response form (e.g. one-click-apply vacancies pass it here).
    if letter:
        box = chat.locator(SEL_CHAT_MSG)
        if box.count() > 0:
            box.first.click()
            box.first.fill(letter)
            chat.wait_for_timeout(800)
            _chat_send(chat)
            chat.wait_for_timeout(2500)

    # 2) The CV PDF via chatik's pre-rendered hidden file input (accepts pdf) —
    #    no "+" click, so no native OS picker can hang the run.
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
    """Send the CV PDF (and, for one-click vacancies, the cover `letter`) in the
    chat if enabled — never failing the (already sent) application when the chat
    step can't complete."""
    if not (attach_cv_in_chat and content.attachment_path):
        return
    try:
        attach_cv_via_chat(page, content.attachment_path, debug_dir, letter)
    except Exception as exc:  # noqa: BLE001 — response already succeeded
        print(f"⚠️  hh: отклик отправлен, но CV/письмо в чат не отправлены: {exc}")


def apply_via_page(page, url: str, content: OutreachContent, answerer=None,
                   attach_cv_in_chat: bool = False, debug_dir=None) -> None:
    page.goto(url, wait_until="domcontentloaded")
    _check_not_blocked(page)
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
        raise ChannelError(f"no apply button on {url}")
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
    # Consent popup for a vacancy in another country — optional.
    if page.locator(SEL_COUNTRY_CONFIRM).count() > 0:
        page.locator(SEL_COUNTRY_CONFIRM).first.click()
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
    # One-click-apply vacancies submit on the apply click itself — no letter form
    # ever renders. Don't hang waiting for a letter box that will never appear:
    # if it's absent, either the response already went through (finish cleanly)
    # or it's an unknown form (capture the DOM and fail clearly, not by timeout).
    if page.locator(SEL_LETTER_INPUT).count() == 0:
        if _already_applied(page):
            print(f"ℹ️  hh: отклик подан в один клик (онлайн-резюме); письмо и CV — в чат: {url}")
            # No letter form was shown, so send the cover letter in the chat too.
            _maybe_attach_cv(page, content, attach_cv_in_chat, debug_dir, letter=content.body)
            return
        _dump_chat_debug(page, debug_dir, "hh_no_letter_field")
        raise ChannelError(
            f"hh: поле письма не появилось и отклик не подтверждён — проверь вручную: {url}")
    page.locator(SEL_LETTER_INPUT).first.fill(content.body)
    page.locator(SEL_SUBMIT).first.click()
    _verify_submitted(page)
    # The application is now sent (online resume included). Optionally attach the
    # PDF as an extra in the chat — never letting its failure fail the application.
    _maybe_attach_cv(page, content, attach_cv_in_chat, debug_dir)


class HeadHunterChannel:
    name = "hh"
    body_limit = 10000          # hh.ru cover-letter length limit
    needs_subject = False

    def __init__(self, storage_state_path: str, headless: bool = False, answerer=None,
                 attach_cv_in_chat: bool = False):
        # answerer(questions, vacancy_context) -> {question_id: {"text"|"choice"}}.
        # None => vacancies with mandatory questions are skipped, not answered.
        # attach_cv_in_chat => after responding, also attach the CV PDF in the chat.
        self._storage_state_path = storage_state_path
        self._headless = headless
        self._answerer = answerer
        self._attach_cv_in_chat = attach_cv_in_chat
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
                       self._attach_cv_in_chat, self._debug_dir)
