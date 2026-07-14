"""External-apply driver: read a company ATS page, classify it, and (for a plain
form) fill + submit with the AI. Isolates all Playwright; the decision logic lives
in app.application (classify_apply / auto_apply) and is tested without a browser.

Automating third-party ATS violates their ToS and risks bans (accepted by user).
"""
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
  const controls = [...document.querySelectorAll('input,select,textarea')]
    .filter(e => !['hidden','submit','button','reset','image'].includes(e.type));
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
  const html = document.documentElement.innerHTML;
  return {
    url: location.href,
    fields,
    file_inputs: document.querySelectorAll('input[type=file]').length,
    iframes: [...document.querySelectorAll('iframe')].map(f=>f.src).filter(Boolean).slice(0,8),
    mailto: [...document.querySelectorAll('a[href^="mailto:"]')].map(a=>a.getAttribute('href')).slice(0,4),
    apply_buttons: [...new Set([...document.querySelectorAll('button,a[role=button],a')]
      .map(b=>norm(b.textContent)).filter(t=>/apply|bewerb|отклик|заявк|application|join/i.test(t)))].slice(0,8),
    captcha: /recaptcha|hcaptcha|turnstile/i.test(html),
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
        if a.is_file and a.value:
            loc.first.set_input_files(a.value)
        elif a.field.tag == "select" and a.choice_index is not None:
            loc.first.select_option(index=a.choice_index)
        elif a.field.type in ("checkbox", "radio"):
            if a.value:
                loc.first.check()
        elif a.value:
            loc.first.fill(a.value)
    if dry_run:
        return
    submit = page.locator(SEL_SUBMIT)
    if submit.count() == 0:
        raise ManualApplyRequired("внешняя форма: не нашёл кнопку отправки, нужен ручной отклик")
    submit.first.click()


def external_apply(page, job_url: str, content, profile, cv_path: str,
                   answerer=None, dry_run: bool = False, email_channel=None,
                   subject_maker=None, vacancy_context: str = "") -> None:
    obs = scrape_form(page)
    route = classify(obs)

    if route is Route.EMAIL:
        _apply_via_email(obs, content, cv_path, email_channel, subject_maker,
                         vacancy_context)
        return
    if route is Route.IFRAME_ATS:
        _enter_ats_iframe(page, obs)
        obs = scrape_form(page)
        route = classify(obs)
    if route is Route.GATED:
        raise ManualApplyRequired(
            f"внешний отклик за гейтом (CAPTCHA/логин), нужен ручной отклик: {obs.url}")
    if route is not Route.FORM:
        raise ManualApplyRequired(
            f"внешняя форма не распознана, нужен ручной отклик: {obs.url}")

    plan = build_plan(obs, profile, cv_path)
    answer_ai_fields(plan, answerer, vacancy_context or content.body)
    missing = plan.unmapped_required()
    if missing:
        raise ManualApplyRequired(
            f"внешняя форма: не заполнены обязательные поля {missing}, "
            f"нужен ручной отклик: {obs.url}")

    # profile.md tells the AI to emit "[brackets]" when unsure; such a value must
    # never reach a real employer. unmapped_required() only guards *required*
    # fields, so an optional field with a placeholder would otherwise slip through.
    placeholders = [a.field.label or a.field.name for a in plan.actions if "[" in a.value]
    if placeholders:
        raise ManualApplyRequired(
            f"внешняя форма: ИИ оставил плейсхолдер в {placeholders}, нужен ручной отклик: {obs.url}")

    fill_and_submit(page, plan, dry_run)
    if dry_run:
        raise ManualApplyRequired(
            f"APPLY_DRY_RUN: форма заполнена, но НЕ отправлена (проверь вручную): {obs.url}")
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
            f"внешняя форма: отправка не подтверждена (форма всё ещё открыта), проверь вручную: {url}")


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
