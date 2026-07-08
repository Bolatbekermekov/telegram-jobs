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


def apply_via_page(page, url: str, content: OutreachContent, answerer=None) -> None:
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
            f"{SEL_COUNTRY_CONFIRM}, {SEL_LETTER_TOGGLE}, {SEL_LETTER_INPUT}", timeout=15000)
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
    page.locator(SEL_LETTER_INPUT).first.fill(content.body)
    page.locator(SEL_SUBMIT).first.click()
    _verify_submitted(page)


class HeadHunterChannel:
    name = "hh"
    body_limit = 10000          # hh.ru cover-letter length limit
    needs_subject = False

    def __init__(self, storage_state_path: str, headless: bool = False, answerer=None):
        # answerer(questions, vacancy_context) -> {question_id: {"text"|"choice"}}.
        # None => vacancies with mandatory questions are skipped, not answered.
        self._storage_state_path = storage_state_path
        self._headless = headless
        self._answerer = answerer
        self._pw = None
        self._browser = None
        self._page = None

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
        apply_via_page(self._page, vacancy_url(target), content, self._answerer)
