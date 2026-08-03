"""External-apply driver: read a company ATS page, classify it, and (for a plain
form) fill + submit with the AI. Isolates all Playwright; the decision logic lives
in app.application (classify_apply / auto_apply) and is tested without a browser.

Automating third-party ATS violates their ToS and risks bans (accepted by user).
"""
import re
from urllib.parse import unquote, urlsplit

from app.application.apply_guard import host_allowed, leaked_secrets
from app.application.auto_apply import answer_ai_fields, build_plan
from app.application.classify_apply import classify, known_ats_iframe
from app.domain.channel import ManualApplyRequired, OutreachContent
from app.domain.page_observation import FieldObs, PageObservation, Route

# Broad submit selector, RU + EN, across ATS themes.
SEL_SUBMIT = (
    "button[type=submit], input[type=submit], "
    "button:has-text('Submit application'), button:has-text('Submit'), "
    "button:has-text('Отправить заявку'), button:has-text('Отправить'), "
    "button:has-text('Send application'), button:has-text('Apply')"
)

# Tags each fillable control with data-af=<idx> (a stable fill handle) and returns
# a compact form snapshot. Mirrors the recon extractor used live on 2026-07-14.
_SCRAPE_JS = r"""() => {
  const norm = s => (s||'').replace(/\s+/g,' ').trim().slice(0,80);
  const labelFor = el => {
    if (el.getAttribute('aria-label')) return norm(el.getAttribute('aria-label'));
    if (el.id) { const l = document.querySelector('label[for="'+el.id+'"]'); if (l) return norm(l.textContent); }
    const l2 = el.closest('label'); if (l2) return norm(l2.textContent);
    if (el.placeholder) return norm(el.placeholder);
    return norm(el.name);
  };
  const isVisible = e => !e.disabled && e.getClientRects().length > 0
    && getComputedStyle(e).visibility !== 'hidden';
  // A file input is a special case: nearly every ATS hides the real <input> and
  // shows a styled button instead — LinkedIn's resume upload does, and it has no
  // visible control at all. Filtering it out by visibility meant the CV was never
  // attached and the required-field check saw nothing missing, so the flow walked
  // into "A resume is required" and clicked the same screen until it gave up
  // (measured live 2026-07-29). Playwright sets files on a hidden input fine, so
  // visibility must not decide whether we can see it. `type=hidden` is still
  // excluded above — that is a different thing from a visually hidden file input.
  const usable = e => e.type === 'file' ? !e.disabled : isVisible(e);
  const controls = [...document.querySelectorAll('input,select,textarea')]
    .filter(e => !['hidden','submit','button','reset','image'].includes(e.type) && usable(e));
  // Radios only mean anything as a group: one question, several buttons. Emitted
  // one at a time they carry no options, so nothing could answer them and a
  // required group came back as "Please make a selection" (measured live on
  // 2026-07-29, job 4434515311). One entry per `name`, options = the buttons'
  // labels, and the question taken from the surrounding fieldset/group.
  const radioGroup = e => [...document.querySelectorAll('input[type=radio]')]
    .filter(r => r.name === e.name);
  // The question a radio group asks, and the text of each button — read from the
  // block that wraps the whole group when the markup gives us nothing else.
  // Ashby ties no <label> to its radios: every button in every group shares one
  // id, carries value="on", and the group's only name is a UUID pair. Read
  // literally that produced a question called
  // "fbb7b4c4-…_b1925c5d-…" with three blank options, so «Gender» and «Marital
  // Status» were invisible to every rule and the form came back "Missing entry
  // for required field" (lead 123, 2026-07-29). The wrapper's innerText is
  // "Gender\nMale\nFemale\nPrefer not to say" — question first, options after.
  const groupBlock = e => {
    const g = radioGroup(e);
    let node = e.parentElement;
    for (let i = 0; i < 8 && node; i++, node = node.parentElement) {
      if (!g.every(r => node.contains(r))) continue;
      const lines = (node.innerText || '').split('\n')
        .map(x => x.trim()).filter(Boolean);
      if (lines.length > g.length) return lines;   // a caption beyond the options
    }
    return null;
  };
  const groupLabel = e => {
    const fs = e.closest('fieldset');
    const lg = fs && fs.querySelector('legend');
    if (lg) return norm(lg.textContent);
    const grp = e.closest('[role=group],[role=radiogroup]');
    if (grp && grp.getAttribute('aria-label')) return norm(grp.getAttribute('aria-label'));
    const lines = groupBlock(e);
    if (lines) return norm(lines[0]);
    return norm(e.name);
  };
  const groupOptions = e => {
    const g = radioGroup(e);
    const own = g.map(r => labelFor(r));
    if (own.some(Boolean)) return own;
    const lines = groupBlock(e);
    if (lines && lines.length >= g.length + 1) {
      return lines.slice(lines.length - g.length).map(norm);
    }
    return own;
  };
  // A consent box's own label is the ANSWER, not the question. LinkedIn renders
  // «Enhesa has my consent to collect, store, and process my data …*» as a
  // paragraph and labels the box itself "Yes" — measured live 2026-07-30 on job
  // 4425082337 (lead 169), where `label[for]` was exactly "Yes" and the sentence
  // sat in the block wrapping the pair. Read literally, no rule in map_field could
  // recognise it, the box stayed unticked, and «Проверить» answered "Select
  // checkbox to proceed" until the walk gave up. This is the same problem
  // groupBlock() already solves for radios: when the control's own markup carries
  // no question, read the block that wraps it.
  //
  // Only a bare answer word sends us looking. A box that already says what it is
  // («Настройка оповещения», the job-alert toggle on the same screen) keeps its
  // own label and stays none of our business.
  const ANSWER_ONLY = /^(yes|no|y|n|да|нет|ja|nein|oui|non|i agree|agree|accept)$/i;
  const checkboxLabel = e => {
    const own = labelFor(e);
    if (own && !ANSWER_ONLY.test(own)) return own;
    let node = e.parentElement;
    for (let i = 0; i < 5 && node; i++, node = node.parentElement) {
      const t = norm(node.innerText);
      if (t.length > own.length) return t;     // the tightest block that says more
    }
    return own;
  };
  const seenRadio = new Set();
  const fields = [];
  controls.forEach((e, i) => {
    e.setAttribute('data-af', String(i));
    if (e.type === 'radio' && e.name) {
      if (seenRadio.has(e.name)) return;
      seenRadio.add(e.name);
      const g = radioGroup(e);
      const picked = g.find(r => r.checked);
      fields.push({
        tag: 'input', type: 'radio', label: groupLabel(e), name: e.name,
        required: g.some(r => r.required || r.getAttribute('aria-required')==='true'),
        options: groupOptions(e),
        value: picked ? labelFor(picked) : '',
        ref: String(i),
      });
      return;
    }
    fields.push({
      tag: e.tagName.toLowerCase(),
      type: (e.type||'').toLowerCase(),
      label: e.type === 'checkbox' ? checkboxLabel(e) : labelFor(e),
      name: e.name||'',
      required: e.required || e.getAttribute('aria-required')==='true',
      options: e.tagName==='SELECT' ? [...e.options].map(o=>norm(o.textContent)) : [],
      // What the field ALREADY holds. LinkedIn's Easy Apply arrives with the
      // account's email and phone country code selected, and without reading
      // that back a prefilled required field looks empty and unfillable.
      // A select reports its chosen option's text, not the option's value
      // attribute, so it can be compared with `options` directly.
      //
      // A checkbox reports its STATE for the same reason. `e.value` is the HTML
      // value attribute, which is "on" by default whether or not the box is
      // ticked — and `value` is what `_satisfied()` reads, so every checkbox on
      // every page came back already-answered and `unmapped_required()` had
      // nothing to report about an untouched one (lead 169, 2026-07-30).
      value: e.tagName==='SELECT'
             ? (e.selectedIndex >= 0 ? norm(e.options[e.selectedIndex].textContent) : '')
             : (e.type === 'checkbox' ? (e.checked ? 'on' : '') : (e.value || '')),
      // A typeahead accepts only a value picked from its own suggestions.
      // LinkedIn's «Location (city)» is one, and typing "Astana" into it is
      // answered with "Please enter a valid answer" — the field looks like a
      // plain text box and behaves like a dropdown.
      combobox: e.getAttribute('role') === 'combobox'
                || ['list','both'].includes(e.getAttribute('aria-autocomplete')),
      ref: String(i),
    });
  });
  const txt = norm(document.body ? document.body.innerText : '');
  return {
    url: location.href,
    fields,
    file_inputs: document.querySelectorAll('input[type=file]').length,
    iframes: [...document.querySelectorAll('iframe')].map(f=>f.src).filter(Boolean).slice(0,8),
    mailto: [...document.querySelectorAll('a[href^="mailto:"]')].map(a=>a.getAttribute('href')).slice(0,4),
    apply_buttons: [...new Set([...document.querySelectorAll('button,a[role=button],a')]
      .map(b=>norm(b.textContent)).filter(t=>/apply|bewerb|отклик|заявк|application|join/i.test(t)))].slice(0,8),
    captcha: !!document.querySelector('iframe[src*="recaptcha/api2/anchor"], iframe[title="reCAPTCHA"], iframe[src*="hcaptcha.com"], iframe[src*="challenges.cloudflare.com"], .cf-turnstile'),
    login_required: (document.querySelector('input[type=password]')!=null)
      && /sign in|log in|register|create account|войти|регистрац/i.test(txt),
    text_excerpt: txt.slice(0,240),
  };
}"""


def observation_to_raw(obs: PageObservation) -> dict:
    """Inverse of _build_observation — used by tests' fake page.evaluate()."""
    return {
        "url": obs.url,
        "fields": [{"tag": f.tag, "type": f.type, "label": f.label, "name": f.name,
                    "required": f.required, "options": f.options, "value": f.value,
                    "combobox": f.combobox, "ref": f.ref}
                   for f in obs.fields],
        "file_inputs": obs.file_inputs, "iframes": obs.iframes,
        "mailto": obs.mailto_links, "apply_buttons": obs.apply_buttons,
        "captcha": obs.captcha, "login_required": obs.login_required,
        "text_excerpt": obs.text_excerpt,
    }


def _build_observation(raw: dict) -> PageObservation:
    fields = [FieldObs(tag=f.get("tag", ""), type=f.get("type", ""),
                       label=f.get("label", ""), name=f.get("name", ""),
                       required=bool(f.get("required")), options=f.get("options") or [],
                       value=f.get("value", "") or "",
                       combobox=bool(f.get("combobox")),
                       ref=f.get("ref", "")) for f in raw.get("fields", [])]
    return PageObservation(
        url=raw.get("url", ""), fields=fields, file_inputs=raw.get("file_inputs", 0),
        iframes=raw.get("iframes", []), mailto_links=raw.get("mailto", []),
        apply_buttons=raw.get("apply_buttons", []), captcha=bool(raw.get("captcha")),
        login_required=bool(raw.get("login_required")),
        text_excerpt=raw.get("text_excerpt", ""))


def scrape_form(page) -> PageObservation:
    return _build_observation(page.evaluate(_SCRAPE_JS))


SEL_SUGGESTION = "[role=option], [role=listbox] li"
# How long an ATS needs to finish re-rendering around a file input after upload.
_FILE_SETTLE_MS = 2000

# What counts as "tick it" for a lone checkbox. One box often stands in for a
# yes/no question («Are you willing to relocate?»), and map_field answers those
# through _yes_no, which returns the STRING "No". Ticking on "any non-empty value"
# then records the opposite of what was decided. Only an affirmative ticks.
_AFFIRMATIVE = frozenset({"true", "yes", "on", "1", "y", "да", "checked"})


def _is_affirmative(value: str) -> bool:
    return (value or "").strip().lower() in _AFFIRMATIVE


def _fill_typeahead(page, box, value: str) -> None:
    """Answer a typeahead by picking from its own list, not by typing at it.

    `.fill()` writes the value straight into the DOM without keystrokes, so the
    suggestion list never opens and the control keeps no chosen item — LinkedIn
    answers that with "Please enter a valid answer" and refuses the step (lead
    126, measured live 2026-07-29: «Location (city)» is `role=combobox`,
    `aria-autocomplete=list`, and typing "Astana" offered eight suggestions).
    Typing character by character is what opens the list.

    If nothing is offered, the typed text stays: some comboboxes do accept free
    text, and where they don't the form says so and the caller reports that.
    """
    box.click(timeout=8000)
    box.fill("", timeout=8000)
    box.type(value, delay=120)
    try:
        page.wait_for_timeout(1500)
    except Exception:  # noqa: BLE001 — fake page has no wait_for_timeout
        pass
    options = page.locator(SEL_SUGGESTION)
    if options.count() > 0:
        options.first.click(timeout=4000)


def _relocate(page, field):
    """Find a control again after the page re-rendered and dropped our data-af tag.

    `data-af` is an attribute we stamp on during the scrape, so a React re-render
    replaces the node and takes the tag with it. Measured on Ashby (2026-07-29):
    setting the first file input re-renders the form, and the REQUIRED «Resume»
    input two nodes later comes back with `af=None`. Re-scraping re-stamps every
    control, so the field can be matched again by what it is rather than by a tag
    it no longer carries.
    """
    try:
        fresh = scrape_form(page)
    except Exception:  # noqa: BLE001
        return None
    for f in fresh.fields:
        same = (f.tag == field.tag and f.type == field.type
                and f.label == field.label and f.name == field.name)
        if same and f.ref:
            return page.locator(f'[data-af="{f.ref}"]')
    return None


_NUMBER_RE = re.compile(r"\d[\d\s.,]*")


def numeric_only(value: str) -> str:
    """The number inside a free-text answer, ready for <input type=number>.

    A model asked "minimum salary in £ per month" answers "£5000", and Playwright
    refuses that outright: "Cannot type text into input[type=number]". On a
    REQUIRED field that refusal parked the whole application (lead 123). Thousands
    separators go; a genuine decimal tail (1-2 digits) survives.
    """
    m = _NUMBER_RE.search(value or "")
    if not m:
        return ""
    raw = m.group(0).strip()
    decimal = re.search(r"[.,](\d{1,2})$", raw)
    whole = re.sub(r"\D", "", raw[:decimal.start()] if decimal else raw)
    if not whole:
        return ""
    return f"{whole}.{decimal.group(1)}" if decimal else whole


def _pause(page, ms: int) -> None:
    try:
        page.wait_for_timeout(ms)
    except Exception:  # noqa: BLE001 — fake pages have no clock
        pass


def _attached_count(loc) -> int:
    """How many files the input actually holds, or -1 when it can't be read."""
    try:
        return int(loc.first.evaluate("el => (el.files && el.files.length) || 0"))
    except Exception:  # noqa: BLE001
        return -1


def fill_fields(page, plan, where: str = "внешняя форма") -> None:
    """Type every planned value into the page. Submits nothing.

    Split out of `fill_and_submit` so LinkedIn's multi-step Easy Apply can reuse
    it per step: that flow fills, advances, and fills again before anything is
    submitted, but the per-widget rules — bounded timeouts, required-field bail,
    optional-field skip — must stay identical across both callers. `where` only
    names the form in the error a human reads.
    """
    # Uploads first, everything else after. Each file upload makes the ATS rebuild
    # the form — Ashby's `setFormValueToFile` answers with a NEW form render id —
    # and every value written to the previous render is discarded with it. Filling
    # in DOM order sent 21 setFormValue calls, most of them to a form that no
    # longer existed, and the Submit that followed fired no request at all
    # (measured on lead 123, 2026-07-29).
    ordered = ([a for a in plan.actions if a.is_file]
               + [a for a in plan.actions if not a.is_file])
    for a in ordered:
        if not a.field.ref:
            continue
        loc = page.locator(f'[data-af="{a.field.ref}"]')
        if loc.count() == 0:
            # Gone from under us — an earlier fill re-rendered the form. Re-scrape
            # and match it again. Skipping silently is what sent an Ashby
            # application with NO resume: the required «Resume» input lost its tag
            # when the file input above it was set, this line dropped it, and
            # `unmapped_required()` had already passed because it reads the PLAN,
            # not the page.
            loc = _relocate(page, a.field)
            if loc is None or loc.count() == 0:
                if a.field.required:
                    raise ManualApplyRequired(
                        f"{where}: обязательное поле "
                        f"«{a.field.label or a.field.name}» исчезло со страницы "
                        "после перерисовки формы, нужен ручной отклик")
                continue
        # Bound every fill so a stray/invisible control can never hang 30s or crash
        # the whole fill. If a REQUIRED field can't be filled, bail to a manual apply
        # (never submit a partial form); an optional one is just skipped.
        try:
            if a.is_file and a.value:
                loc.first.set_input_files(a.value, timeout=8000)
                # Let the upload land before touching anything else. An ATS
                # re-renders the form around a file input, and without this pause
                # the NEXT field is looked up mid-swap.
                _pause(page, _FILE_SETTLE_MS)
                if a.field.required:
                    # Verify on a FRESHLY located element, never on the handle we
                    # just used: measured on Ashby (2026-07-29) the file lands on
                    # the node React is about to discard, so the old handle happily
                    # reports 1 file while the live input holds none — and the
                    # application goes out without the resume it requires.
                    live = _relocate(page, a.field) or loc
                    if _attached_count(live) == 0:
                        live.first.set_input_files(a.value, timeout=8000)
                        _pause(page, _FILE_SETTLE_MS)
                        live = _relocate(page, a.field) or live
                    if _attached_count(live) == 0:
                        raise ManualApplyRequired(
                            f"{where}: резюме не прикрепилось к обязательному полю "
                            f"«{a.field.label or a.field.name}», нужен ручной отклик")
            elif a.field.tag == "select" and a.choice_index is not None:
                loc.first.select_option(index=a.choice_index, timeout=8000)
            elif a.field.type == "radio" and a.choice_index is not None:
                # The plan holds one action per GROUP, addressed by the first
                # button's ref; the answer is which button of that group to press.
                # Located by name rather than by ref so the index means the same
                # thing it meant when the group was scraped — falling back to the
                # ref when the name doesn't survive as a selector.
                group = page.locator(f'input[type=radio][name="{a.field.name}"]')
                target = (group.nth(a.choice_index)
                          if group.count() > a.choice_index else loc.first)
                # force=True: the real radio is hidden behind a styled label on
                # LinkedIn (and on most ATS themes), and Playwright will not act
                # on an invisible control without it. Nothing is guessed here —
                # the element was found by name and index, only its visibility
                # is being overridden.
                target.check(force=True, timeout=8000)
            elif a.field.type in ("checkbox", "radio"):
                if _is_affirmative(a.value):
                    # force=True for the same reason as the radio group above: the
                    # real box is hidden behind a styled label. Without it `check`
                    # times out, and on an OPTIONAL field that exception is
                    # swallowed — which is how «I consent» stayed unticked while
                    # the form answered "Select checkbox to proceed" and the step
                    # never advanced (lead 126, measured live 2026-07-29). LinkedIn
                    # marks that box `required=false` in the DOM and demands it
                    # anyway, so nothing upstream flagged it either.
                    loc.first.check(force=True, timeout=8000)
            elif a.field.combobox and a.value:
                _fill_typeahead(page, loc.first, a.value)
            elif a.value:
                text = a.value
                if a.field.type == "number":
                    text = numeric_only(text)
                    if not text and a.field.required:
                        raise ManualApplyRequired(
                            f"{where}: в числовое поле "
                            f"«{a.field.label or a.field.name}» нечего вписать "
                            f"(ответ был {a.value[:40]!r}), нужен ручной отклик")
                loc.first.fill(text, timeout=8000)
        except ManualApplyRequired:
            # A diagnosis we made deliberately (the resume never attached, a
            # required control vanished). Let it out intact — the generic handler
            # below would overwrite it with "не смог заполнить поле", which points
            # the human at the wrong thing.
            raise
        except Exception:  # noqa: BLE001 — hidden/odd widget must not hang or crash the fill
            if a.field.required:
                raise ManualApplyRequired(
                    f"{where}: не смог заполнить обязательное поле "
                    f"«{a.field.label or a.field.name}», нужен ручной отклик")
            continue


def fill_and_submit(page, plan, dry_run: bool) -> None:
    fill_fields(page, plan)
    if dry_run:
        return
    submit = page.locator(SEL_SUBMIT)
    if submit.count() == 0:
        raise ManualApplyRequired("внешняя форма: не нашёл кнопку отправки, нужен ручной отклик")
    btn = submit.first
    try:
        btn.scroll_into_view_if_needed(timeout=2000)
    except Exception:  # noqa: BLE001 — best-effort; some fakes/pages have no scroll
        pass
    # Native el.click() first. A synthetic Playwright click on Ashby's «Submit
    # Application» does NOTHING — measured live 2026-07-29: no navigation, no
    # error, no change for 30 seconds, button still enabled. The same call as
    # el.click() submitted immediately. A native click also walks past the overlay
    # problem the fallback below was written for, since it needs no hit point.
    try:
        btn.evaluate("el => el.click()", timeout=8000)
        return
    except Exception:  # noqa: BLE001 — stale handle / no JS: fall back to a real click
        pass
    try:
        # Cap the click: on some ATS (e.g. Angular/PrimeNG) a <p-dialog> overlay
        # intercepts pointer events, and a default click auto-waits 30s then fails,
        # burning the lead. Bounded click -> manual apply instead of a 30s hang.
        btn.click(timeout=8000)
    except Exception:  # noqa: BLE001 — intercepted by an overlay / not actionable
        raise ManualApplyRequired(
            "внешняя форма: кнопка отправки перехвачена оверлеем (модалка ATS), нужен ручной отклик")


def scrape_until_ready(page, attempts: int = 6, interval_ms: int = 1500):
    """Re-scrape while the page still classifies as NONE. Many ATS render their
    apply form client-side, a beat after navigation — a single early scrape sees
    an empty page and wrongly gives up. Poll until the page is actionable
    (FORM/EMAIL/IFRAME_ATS/GATED) or the attempts run out; return (obs, route)."""
    obs = scrape_form(page)
    route = classify(obs)
    for _ in range(attempts - 1):
        if route is not Route.NONE:
            break
        page.wait_for_timeout(interval_ms)
        obs = scrape_form(page)
        route = classify(obs)
    return obs, route


# Some ATS hide the form behind an "Apply"/"Easy Apply" button that opens it in a
# modal or a later step (e.g. Ceipal). On an otherwise-empty page we click one and
# re-scrape for the revealed form.
_REVEAL_SEL = (
    "button:has-text('Easy Apply'), a:has-text('Easy Apply'), "
    "button:has-text('Apply now'), a:has-text('Apply now'), "
    "button:has-text('Start application'), button:has-text('Подать заявку'), "
    "button:has-text('Apply'), a:has-text('Apply')"
)


def _reveal_apply_form(page) -> bool:
    """Click an 'Apply'/'Easy Apply' control to surface a form hidden behind it
    (often a modal). Best-effort: tries the first few visible candidates, scrolls
    into view, force-clicks if a normal click is intercepted. Returns True if a
    click landed (the caller then re-scrapes for the revealed form)."""
    try:
        loc = page.locator(_REVEAL_SEL)
        n = min(loc.count(), 4)
    except Exception:  # noqa: BLE001
        return False
    for i in range(n):
        el = loc.nth(i)
        try:
            if not el.is_visible():
                continue
            el.scroll_into_view_if_needed(timeout=2000)
            el.click(timeout=5000)
            return True
        except Exception:  # noqa: BLE001
            try:
                el.click(timeout=2000, force=True)
                return True
            except Exception:  # noqa: BLE001
                continue
    return False


# An apply path gated behind account creation / sign-in — the URL or a password
# field gives it away. We can't auto-fill these; skip with a clear reason so the
# sheet records "requires Sign Up / Login".
_AUTH_URL_RE = re.compile(
    r"/(register|sign[-_]?up|signup|sign[-_]?in|signin|log[-_]?in|login|auth)(/|\?|#|$)",
    re.I)


def _requires_signup_or_login(page) -> bool:
    try:
        if _AUTH_URL_RE.search(page.url or ""):
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        return page.locator("input[type=password]").count() > 0
    except Exception:  # noqa: BLE001
        return False


# A dead or closed job link — the page is gone (404) or the posting stopped
# accepting applications. Detected from the title/body so the sheet note reads
# "страница недоступна / вакансия неактуальна" instead of "форма не распознана".
_GONE_RE = re.compile(
    r"no longer (available|accepting|active)"
    r"|(position|role|job|vacancy|posting) (has been |is )?(closed|filled|expired|removed)"
    r"|not accepting applications|page (not found|does ?n'?t exist)|404 error"
    r"|вакансия (снят|закрыт|не найден|неактивн|больше не)|страница не найдена|больше не принима",
    re.I)


def _page_unavailable(page) -> bool:
    text = ""
    try:
        text += (page.title() or "") + " "
    except Exception:  # noqa: BLE001
        pass
    try:
        text += page.locator("body").inner_text(timeout=3000)[:4000]
    except Exception:  # noqa: BLE001
        pass
    return bool(_GONE_RE.search(text))


# Подпись поля-загрузки, которое просит сопроводительное письмо.
_COVER_LETTER_FILE_RE = re.compile(r"cover\s*letter|motivation|сопровод", re.I)


def _wants_cover_letter_file(obs) -> bool:
    """Есть ли на форме загрузка сопроводительного письма.

    Спрашиваем до сборки PDF: tectonic это отдельный процесс на несколько
    секунд, и запускать его на каждой форме, где такого поля нет, незачем.
    """
    return any(f.type == "file" and _COVER_LETTER_FILE_RE.search(f"{f.label} {f.name}")
               for f in obs.fields)


def external_apply(page, job_url: str, content, profile, cv_path: str,
                   answerer=None, dry_run: bool = False, email_channel=None,
                   subject_maker=None, vacancy_context: str = "") -> None:
    obs, route = scrape_until_ready(page)
    if route is Route.NONE and _reveal_apply_form(page):
        obs, route = scrape_until_ready(page)   # form opened in a modal / next step

    if route is Route.EMAIL:
        _apply_via_email(obs, content, cv_path, email_channel, subject_maker,
                         vacancy_context, dry_run)
        return
    if route is Route.IFRAME_ATS:
        _enter_ats_iframe(page, obs)
        obs, route = scrape_until_ready(page)
    if route is Route.GATED:
        raise ManualApplyRequired(f"за гейтом (CAPTCHA/логин): {obs.url}")
    if route is not Route.FORM:
        if _requires_signup_or_login(page):
            raise ManualApplyRequired(f"требует Sign Up / Login: {obs.url}")
        if _page_unavailable(page):
            raise ManualApplyRequired(f"страница недоступна / вакансия неактуальна: {obs.url}")
        raise ManualApplyRequired(f"форма не распознана: {obs.url}")

    # Checked here, on the page that actually holds the form — not on job_url.
    # An IFRAME_ATS lands on a company page but fills the vendor's form (obs.url is
    # the vendor after _enter_ats_iframe), and the EMAIL route returns above without
    # filling anything. Only a form we are about to fill and submit needs the host
    # to be one we recognise: the page supplies the labels that reach the model and
    # receives whatever it answers.
    if not host_allowed(obs.url):
        raise ManualApplyRequired(f"незнакомый сайт, заполни вручную: {obs.url}")

    # Сопроводительное письмо файлом. Собирается ИЗ УЖЕ НАПИСАННОГО письма, то
    # есть ничего заново не выдумывается; если tectonic не установлен или сборка
    # не удалась, вернётся пустая строка и поле останется незаполненным — ровно
    # как было до этой возможности.
    cover_letter = ""
    if _wants_cover_letter_file(obs):
        from app.infrastructure.cover_letter_pdf import render_cover_letter_pdf
        cover_letter = render_cover_letter_pdf(content.body)
    plan = build_plan(obs, profile, cv_path, cover_letter_path=cover_letter)
    answer_ai_fields(plan, answerer, vacancy_context or content.body)
    missing = plan.unmapped_required()
    if missing:
        raise ManualApplyRequired(
            f"не заполнены обязательные поля {missing}: {obs.url}")

    # profile.md tells the AI to emit "[brackets]" when unsure; such a value must
    # never reach a real employer. unmapped_required() only guards *required*
    # fields, so an optional field with a placeholder would otherwise slip through.
    placeholders = [a.field.label or a.field.name for a in plan.actions if "[" in a.value]
    if placeholders:
        raise ManualApplyRequired(
            f"ИИ оставил плейсхолдер {placeholders}: {obs.url}")

    # The ATS collects contact details in their own fields, so a model-written
    # answer restating them means the page asked for them. Checked on AI answers
    # only — profile-sourced fields are supposed to carry these values.
    for a in plan.ai_fields:
        leaked = leaked_secrets(a.value, profile)
        if leaked:
            raise ManualApplyRequired(
                f"ответ ИИ содержит личные данные {leaked} "
                f"(поле «{a.field.label or a.field.name}») — проверь вручную: {obs.url}")

    submit_before = _submit_count(page)
    fill_and_submit(page, plan, dry_run)
    if dry_run:
        raise ManualApplyRequired(
            f"DRY_RUN: заполнено, НЕ отправлено — проверь вручную: {obs.url}")
    _verify_submitted(page, obs.url, submit_before)


# What an ATS says once it has the application. Kept to phrases that only appear
# after a submit — "apply" and "application" alone are all over an unsubmitted
# form, and a false positive here marks an unsent lead `sent` forever.
_SUBMITTED_RE = re.compile(
    r"thank you for (?:applying|your application)|thanks for applying|"
    r"application (?:submitted|received|complete)|"
    r"we(?:'ve| have) received your application|your application (?:was|has been) sent|"
    r"заявка (?:отправлена|принята|получена)|спасибо за (?:отклик|заявку)",
    re.IGNORECASE)
# An Ashby submit uploads the CV and then re-renders; six seconds was not enough
# to see the outcome, and "no signal yet" was being reported as "no confirmation".
# The ATS refusing us as a bot. Ashby answers a submitted application with
# "Your application submission was flagged as possible spam" and keeps the form;
# the page also carries a reCAPTCHA token field. This is bot detection, not a
# fixable form problem — say so plainly and hand the lead to the human.
_BOT_BLOCKED_RE = re.compile(
    r"flagged as (?:possible )?spam|we could ?n[o']t submit your application|"
    r"suspected (?:bot|automation)|verify (?:you are|you're) (?:a )?human|"
    r"похоже на спам|подтвердите, что вы не робот",
    re.IGNORECASE)
_VERIFY_ATTEMPTS = 10
_VERIFY_INTERVAL_MS = 1500


def _page_text(page) -> str:
    """Head AND tail of the page text.

    A verdict banner lands at the BOTTOM of a long application page — Ashby's
    "flagged as possible spam" sits after the whole job description — so reading
    only the first few thousand characters saw none of it, and a refusal we had
    already taught the code to recognise still surfaced as "no confirmation".
    """
    try:
        text = page.evaluate(
            "() => { const t = document.body.innerText || '';"
            " return t.length <= 8000 ? t : t.slice(0, 4000) + '\\n' + t.slice(-4000); }")
    except Exception:  # noqa: BLE001
        return ""
    return text if isinstance(text, str) else ""


def _submit_count(page) -> int:
    try:
        return page.locator(SEL_SUBMIT).count()
    except Exception:  # noqa: BLE001
        return -1


def _verify_submitted(page, url: str, submit_before: int = -1) -> None:
    """Confirm the application landed, and say so honestly when we can't tell.

    The old check was "is a submit button still on the page after 2 seconds",
    which is wrong twice over. SEL_SUBMIT matches `button:has-text('Apply')`, and
    a confirmation page keeps buttons like that; and two seconds is short for an
    SPA. Every Ashby application came back "отправка не подтверждена" — leads 119,
    127, 128, 129 — while the click had in fact gone through, so the note told the
    human to apply again by hand.

    So: look for a POSITIVE signal — the page says it received the application,
    or navigated, or the form we filled is gone — and poll for it instead of
    glancing once. If none appears, the outcome is genuinely unknown, and the
    message has to say that rather than "not submitted": a second application to
    the same company is the cost of getting this wrong.
    """
    before = url
    for attempt in range(_VERIFY_ATTEMPTS):
        try:
            page.wait_for_timeout(_VERIFY_INTERVAL_MS)
        except Exception:  # noqa: BLE001 — fake page has no wait_for_timeout
            pass
        if _SUBMITTED_RE.search(_page_text(page)):
            return
        try:
            if (page.url or before) != before:
                return                       # navigated away from the form
        except Exception:  # noqa: BLE001
            pass
        try:
            if not scrape_form(page).fields:
                return                       # the form itself is gone
        except Exception:  # noqa: BLE001
            pass
        # The exact button we pressed is gone. Weaker than a thank-you page, but
        # unambiguous when there WAS one and now there is none — and unlike the old
        # check this compares against a count taken before the click, so a page
        # whose only match was a stray «Apply» link can't fake it.
        if submit_before > 0 and _submit_count(page) == 0:
            return
        if attempt == _VERIFY_ATTEMPTS - 1:
            break
    said = _visible_error(page)
    if _BOT_BLOCKED_RE.search(said) or _BOT_BLOCKED_RE.search(_page_text(page)):
        raise ManualApplyRequired(
            "ATS отклонил отправку как автоматическую (антибот/captcha) — "
            f"эту заявку можно подать только вручную: {url}")
    if said:
        raise ManualApplyRequired(f"форма не приняла: {said} — {url}")
    raise ManualApplyRequired(
        "кнопка отправки нажата, но подтверждения не видно — ВОЗМОЖНО, ЗАЯВКА "
        f"УЖЕ УШЛА, проверь почту прежде чем откликаться повторно: {url}")


def _visible_error(page) -> str:
    """Text of a validation message on the page, or "" — the honest failure case."""
    try:
        # `[class*=error i]`, not `.error`: every modern ATS ships hashed class
        # names (`_errorBanner_1e3gg_32`), which an exact class selector misses.
        errs = page.locator("[role=alert], [aria-invalid='true'], "
                            "[class*=error i], [class*=Error]")
        n = min(errs.count(), 5)
    except Exception:  # noqa: BLE001
        return ""
    for i in range(n):
        try:
            said = (errs.nth(i).inner_text(timeout=1500) or "").strip()
        except Exception:  # noqa: BLE001
            continue
        if said:
            return said[:120]
    return ""


def _apply_via_email(obs, content, cv_path, email_channel, subject_maker,
                     vacancy_context, dry_run: bool = False) -> None:
    if email_channel is None:
        raise ManualApplyRequired(
            f"внешний отклик по email, но email-канал не настроен (SMTP): {obs.url}")
    addr = _mailto_address(obs.mailto_links[0])
    if not addr:
        raise ManualApplyRequired(f"внешний отклик по email: не разобрал адрес: {obs.url}")
    subject = (subject_maker(vacancy_context) if subject_maker else "Application").strip()
    if dry_run:
        # Письмо и ЕСТЬ подача заявки, поэтому dry_run обязан её остановить —
        # ровно как он останавливает нажатие Submit у формы. Адрес и тема уже
        # разобраны, так что пробный прогон по-прежнему показывает, что не так.
        raise ManualApplyRequired(
            f"DRY_RUN: письмо на {addr} подготовлено, НЕ отправлено: {obs.url}")
    email_channel.send(addr, OutreachContent(
        subject=subject or "Application", body=content.body, attachment_path=cv_path))


def _mailto_address(mailto: str) -> str:
    # "mailto:hr@x.com?subject=..." -> "hr@x.com"
    rest = mailto[len("mailto:"):] if mailto.lower().startswith("mailto:") else mailto
    addr = urlsplit(rest).path or rest.split("?", 1)[0]
    return unquote(addr).strip()


def _enter_ats_iframe(page, obs) -> None:
    """The application form is embedded from a known ATS (e.g. Comeet). Navigate the
    page directly to the iframe's own URL so a re-scrape sees a plain form. The src
    already carries the position token, so the form loads standalone."""
    src = known_ats_iframe(obs.iframes)
    if not src:
        raise ManualApplyRequired(f"встроенный ATS не распознан: {obs.url}")
    # wait_until="domcontentloaded" fires before a client-rendered ATS (Comeet/React)
    # mounts its form, so a re-scrape can see an empty page. Wait for full load plus a
    # short settle so the form exists before scrape_form runs again.
    page.goto(src, wait_until="load")
    try:
        page.wait_for_timeout(1500)
    except Exception:  # noqa: BLE001 — fake page has no wait_for_timeout
        pass
