"""External-apply driver: read a company ATS page, classify it, and (for a plain
form) fill + submit with the AI. Isolates all Playwright; the decision logic lives
in app.application (classify_apply / auto_apply) and is tested without a browser.

Automating third-party ATS violates their ToS and risks bans (accepted by user).
"""
import re
from urllib.parse import unquote, urlsplit

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
  const controls = [...document.querySelectorAll('input,select,textarea')]
    .filter(e => !['hidden','submit','button','reset','image'].includes(e.type) && isVisible(e));
  const fields = controls.map((e, i) => {
    e.setAttribute('data-af', String(i));
    return {
      tag: e.tagName.toLowerCase(),
      type: (e.type||'').toLowerCase(),
      label: labelFor(e),
      name: e.name||'',
      required: e.required || e.getAttribute('aria-required')==='true',
      options: e.tagName==='SELECT' ? [...e.options].map(o=>norm(o.textContent)) : [],
      ref: String(i),
    };
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
                    "required": f.required, "options": f.options, "ref": f.ref}
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
                       ref=f.get("ref", "")) for f in raw.get("fields", [])]
    return PageObservation(
        url=raw.get("url", ""), fields=fields, file_inputs=raw.get("file_inputs", 0),
        iframes=raw.get("iframes", []), mailto_links=raw.get("mailto", []),
        apply_buttons=raw.get("apply_buttons", []), captcha=bool(raw.get("captcha")),
        login_required=bool(raw.get("login_required")),
        text_excerpt=raw.get("text_excerpt", ""))


def scrape_form(page) -> PageObservation:
    return _build_observation(page.evaluate(_SCRAPE_JS))


def fill_and_submit(page, plan, dry_run: bool) -> None:
    for a in plan.actions:
        if not a.field.ref:
            continue
        loc = page.locator(f'[data-af="{a.field.ref}"]')
        if loc.count() == 0:
            continue
        # Bound every fill so a stray/invisible control can never hang 30s or crash
        # the whole fill. If a REQUIRED field can't be filled, bail to a manual apply
        # (never submit a partial form); an optional one is just skipped.
        try:
            if a.is_file and a.value:
                loc.first.set_input_files(a.value, timeout=8000)
            elif a.field.tag == "select" and a.choice_index is not None:
                loc.first.select_option(index=a.choice_index, timeout=8000)
            elif a.field.type in ("checkbox", "radio"):
                if a.value:
                    loc.first.check(timeout=8000)
            elif a.value:
                loc.first.fill(a.value, timeout=8000)
        except Exception:  # noqa: BLE001 — hidden/odd widget must not hang or crash the fill
            if a.field.required:
                raise ManualApplyRequired(
                    f"внешняя форма: не смог заполнить обязательное поле "
                    f"«{a.field.label or a.field.name}», нужен ручной отклик")
            continue
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


def external_apply(page, job_url: str, content, profile, cv_path: str,
                   answerer=None, dry_run: bool = False, email_channel=None,
                   subject_maker=None, vacancy_context: str = "") -> None:
    obs, route = scrape_until_ready(page)
    if route is Route.NONE and _reveal_apply_form(page):
        obs, route = scrape_until_ready(page)   # form opened in a modal / next step

    if route is Route.EMAIL:
        _apply_via_email(obs, content, cv_path, email_channel, subject_maker,
                         vacancy_context)
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

    plan = build_plan(obs, profile, cv_path)
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

    fill_and_submit(page, plan, dry_run)
    if dry_run:
        raise ManualApplyRequired(
            f"DRY_RUN: заполнено, НЕ отправлено — проверь вручную: {obs.url}")
    _verify_submitted(page, obs.url)


def _verify_submitted(page, url: str) -> None:
    try:
        page.wait_for_timeout(2000)
    except Exception:  # noqa: BLE001 — fake page has no wait_for_timeout
        pass
    try:
        still_on_form = page.locator(SEL_SUBMIT).count() > 0
    except Exception:  # noqa: BLE001
        still_on_form = False
    if still_on_form:
        raise ManualApplyRequired(
            f"отправка не подтверждена (форма всё ещё открыта): {url}")


def _apply_via_email(obs, content, cv_path, email_channel, subject_maker,
                     vacancy_context) -> None:
    if email_channel is None:
        raise ManualApplyRequired(
            f"внешний отклик по email, но email-канал не настроен (SMTP): {obs.url}")
    addr = _mailto_address(obs.mailto_links[0])
    if not addr:
        raise ManualApplyRequired(f"внешний отклик по email: не разобрал адрес: {obs.url}")
    subject = (subject_maker(vacancy_context) if subject_maker else "Application").strip()
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
