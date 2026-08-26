"""External-apply driver: read a company ATS page, classify it, and (for a plain
form) fill + submit with the AI. Isolates all Playwright; the decision logic lives
in app.application (classify_apply / auto_apply) and is tested without a browser.

Automating third-party ATS violates their ToS and risks bans (accepted by user).
"""
import re
from urllib.parse import unquote, urlsplit

from app.application.apply_guard import (
    host_or_vendor_allowed, leaked_secrets, vendor_behind,
)
from app.application.hidden_date import wants_availability_date
from app.application.auto_apply import (
    COVER_LETTER_RE, _match_choice, answer_ai_fields, build_plan,
    field_is_required as _required,
)
from app.application.classify_apply import classify, known_ats_iframe
from app.domain.ats_embed import greenhouse_embed_url, vendor_apply_url
from app.infrastructure.widgets.choice import pick_choice as _pick_choice
from app.infrastructure.widgets.combobox import (
    _best, combobox_options as _combobox_options, fill_combobox as _fill_combobox,
)
from app.infrastructure.widgets.file_upload import attach_file as _attach_file
from app.domain.channel import ManualApplyRequired, OutreachContent
from app.domain.availability import availability_iso
from app.domain.legal_page import looks_like_legal_page
# `page_is_gone` живёт в домене и переэкспортируется отсюда — тем же приёмом,
# каким `vacancy_fetcher` переэкспортирует предикаты из `vacancy_text`. Правило
# чисто строковое, и спрашивает его теперь не только канал: цикл отправки
# спрашивает то же самое ДО генерации письма, обычным GET. Имя остаётся здесь,
# чтобы уже написанные вызовы (и тесты на снятых живьём строках) не переезжали.
from app.domain.page_gone import (  # noqa: F401 — переэкспорт, см. выше
    GONE_NOTE, page_is_gone,
)
from app.domain.page_observation import FieldObs, PageObservation, Route

# Сколько ждать на форме вендора после перехода: она рисуется скриптом.
_EMBED_SETTLE_MS = 3000

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
  // `aria-hidden` — то, чем страница сама говорит «это не поле для человека».
  // Новая форма Greenhouse рисует каждый выпадающий вопрос ПАРОЙ: настоящий
  // role=combobox с подписью и второй, безымянный вход
  // `<input required tabindex="-1" aria-hidden="true" class="…requiredInput">`,
  // существующий только чтобы браузер ругался на пустой выбор. Замер 2026-08-24
  // на вакансиях N26 и Datadog: 26 «полей» вместо 13 вопросов, у каждого второго
  // подпись пустая — и именно они попадали в «не заполнены обязательные поля»,
  // срывая отправку уже готовой анкеты.
  // Проверяется НЕ пустая подпись: пустая бывает и у настоящего поля, а
  // aria-hidden ставит сам вендор и означает ровно то, что нам нужно.
  // Файл — исключение, как и в isVisible ниже: почти каждый ATS прячет реальный
  // input[type=file] за своей кнопкой, и заявка без резюме этим уже кончалась.
  const usable = e => e.type === 'file' ? !e.disabled
    : (e.getAttribute('aria-hidden') !== 'true' && isVisible(e));
  const controls = [...document.querySelectorAll('input,select,textarea')]
    .filter(e => !['hidden','submit','button','reset','image'].includes(e.type) && usable(e));
  // Radios only mean anything as a group: one question, several buttons. Emitted
  // one at a time they carry no options, so nothing could answer them and a
  // required group came back as "Please make a selection" (measured live on
  // 2026-07-29, job 4434515311). One entry per `name`, options = the buttons'
  // labels, and the question taken from the surrounding fieldset/group.
  // Одна группа = один вопрос. Для радиокнопок это было всегда; чекбоксы Lever
  // задают вопрос с НЕСКОЛЬКИМИ ответами тем же приёмом — общий `name`, — а
  // читались поштучно: замер 2026-08-24 на вакансии CoinsPaid дал «React 16 or
  // earlier», «React 17+», «React 18+» как три отдельных обязательных поля, у
  // каждого вместо вопроса стоял его же вариант. Ответить на такое нечем.
  const sameGroup = e => [...document.querySelectorAll('input[type=' + e.type + ']')]
    .filter(r => r.name === e.name);
  const radioGroup = sameGroup;
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
  const seenGroup = new Set();
  const fields = [];
  controls.forEach((e, i) => {
    e.setAttribute('data-af', String(i));
    // Радиокнопка — вопрос по построению, даже одинокая. Чекбокс одинокий — это
    // согласие, у которого подпись и есть вопрос («Acme has my consent…»), и
    // сгруппировать его значило бы подменить вопрос ответом «Yes»; поэтому для
    // чекбоксов группа начинается с двух.
    if (e.name && (e.type === 'radio'
                   || (e.type === 'checkbox' && sameGroup(e).length > 1))) {
      const key = e.type + '|' + e.name;
      if (seenGroup.has(key)) return;
      seenGroup.add(key);
      const g = sameGroup(e);
      const picked = g.find(r => r.checked);
      fields.push({
        tag: 'input', type: e.type, label: groupLabel(e), name: e.name,
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


# How long an ATS needs to finish re-rendering around a file input after upload.
_FILE_SETTLE_MS = 2000

# What counts as "tick it" for a lone checkbox. One box often stands in for a
# yes/no question («Are you willing to relocate?»), and map_field answers those
# through _yes_no, which returns the STRING "No". Ticking on "any non-empty value"
# then records the opposite of what was decided. Only an affirmative ticks.
_AFFIRMATIVE = frozenset({"true", "yes", "on", "1", "y", "да", "checked"})


def _is_affirmative(value: str) -> bool:
    return (value or "").strip().lower() in _AFFIRMATIVE


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


def fill_fields(page, plan, where: str = "внешняя форма", profile=None) -> None:
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
                if _required(a.field):
                    raise ManualApplyRequired(
                        f"{where}: обязательное поле "
                        f"«{a.field.label or a.field.name}» исчезло со страницы "
                        "после перерисовки формы, нужен ручной отклик")
                continue
        # Bound every fill so a stray/invisible control can never hang 30s or crash
        # the whole fill. If a REQUIRED field can't be filled, bail to a manual apply
        # (never submit a partial form); an optional one is just skipped.
        # `_required`, а не `a.field.required`: разметка про обязательность врёт.
        # У Teamtailor атрибут стоит у одного поля из девятнадцати, у Zalando и
        # Personio — ни у одного, а обязательность написана словами в подписи
        # (замер 2026-08-25, 144 поля). Решение «прерывать или пропустить» должно
        # читать то же, что читает `unmapped_required`, иначе заполнение молча
        # пройдёт мимо поля, которое эта проверка потом сочтёт обязательным.
        try:
            if a.is_file and a.value:
                # Установка файла, ожидание и повторная попытка — внутри виджета.
                # Здесь их больше нет намеренно: прежняя проверка читала
                # `el.files.length`, а Teamtailor (Dropzone.js) забирает FileList
                # и УДАЛЯЕТ вход из DOM, так что счётчик там ноль ВСЕГДА — даже
                # когда файл уже улетел в хранилище работодателя с ответом 201.
                # Замер 2026-08-24 на вакансии BlueThrone: лид #419 объявлялся
                # непрошедшим при готовой к отправке форме, а перед этим резюме
                # успевало загрузиться ДВАЖДЫ — вторая копия от «повторной
                # попытки». Чем прикрепление доказывается теперь, см. виджет.
                if not _attach_file(page, loc, a.value) and _required(a.field):
                    raise ManualApplyRequired(
                        f"{where}: резюме не прикрепилось к обязательному полю "
                        f"«{a.field.label or a.field.name}», нужен ручной отклик")
            elif a.field.tag == "select" and a.choice_index is not None:
                loc.first.select_option(index=a.choice_index, timeout=8000)
            elif (a.field.type in ("radio", "checkbox")
                  and a.choice_index is not None):
                # План хранит одно действие на ГРУППУ и номер выбранного
                # варианта; группу и номер разбирает сам виджет — он считает их
                # ровно так же, как скрапер, иначе номер укажет на чужую кнопку.
                #
                # `check(force=True)` жил здесь и ронял прогон: на живой форме
                # Recruitee кнопка спрятана как `clip:rect(0,0,0,0)` размером
                # 1×1, и в HEADED Chrome клик до неё не доходит — «Clicking the
                # checkbox did not change its state». В headless тот же вызов
                # проходит, поэтому тесты молчали, а прогон (BROWSER_HEADLESS по
                # умолчанию false) падал на лиде #418.
                if not _pick_choice(page, loc, value=a.value,
                                    index=a.choice_index):
                    if _required(a.field):
                        raise ManualApplyRequired(
                            f"{where}: не выбрался вариант "
                            f"«{a.value or a.choice_index}» в обязательном поле "
                            f"«{a.field.label or a.field.name}», нужен ручной отклик")
                    continue
            elif a.field.type in ("checkbox", "radio"):
                if _is_affirmative(a.value):
                    # Одиночное согласие прячут тем же приёмом, и мимо той же
                    # ямы: «I consent» оставалось непоставленным, форма отвечала
                    # "Select checkbox to proceed", и шаг не продвигался (лид
                    # 126, замер 2026-07-29). LinkedIn помечает эту галочку
                    # `required=false` и требует всё равно, поэтому отказ здесь
                    # виден только по самой форме — молчать о нём нельзя.
                    if not _pick_choice(page, loc, index=0):
                        raise ManualApplyRequired(
                            f"{where}: не поставилась галочка "
                            f"«{a.field.label or a.field.name}», нужен ручной отклик")
            elif a.field.combobox and a.value:
                # Прежний путь искал подсказки ПО ВСЕЙ СТРАНИЦЕ, а на каждой
                # форме Greenhouse рядом с «Phone» висит intl-tel-input со
                # скрытым списком 244 стран. Замер 2026-08-24: на странице 254
                # вариантов, первый — невидимая «Afghanistan», клик уходил туда,
                # ждал видимости 4 секунды и падал. Общий except выдавал ровно
                # «не смог заполнить обязательное поле» — так умерли N26 на
                # «Location (City)*» и Datadog на «School*».
                # Виджет ищет список только по `aria-controls` СВОЕГО поля и
                # ждёт не время, а появление подходящего варианта: серверные
                # подсказки приходят через 1–3 секунды, а до тех пор в меню
                # висят ответы на прошлый запрос.
                if (not _fill_combobox(page, loc, a.value)
                        and not _pick_any_from_roster(page, loc, a.field, profile)
                        and _required(a.field)):
                    raise ManualApplyRequired(
                        f"{where}: не выбрался вариант «{a.value[:40]}» в "
                        f"обязательном поле «{a.field.label or a.field.name}», "
                        "нужен ручной отклик")
            elif a.value:
                text = a.value
                if a.field.type == "number":
                    text = numeric_only(text)
                    if not text and _required(a.field):
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
            if _required(a.field):
                raise ManualApplyRequired(
                    f"{where}: не смог заполнить обязательное поле "
                    f"«{a.field.label or a.field.name}», нужен ручной отклик")
            continue

    for label in fill_hidden_required_dates(page, profile):
        print(f"   ↳ проставил дату выхода в скрытое обязательное поле: {label}")


# Скрытое обязательное поле даты выхода. Скрапер читает только видимые контролы,
# поэтому такого поля план не видит вовсе — а ATS его требует и отправку без
# него отклоняет (BlueThrone, лид #419: блок `hidden max-h-0`, не раскрывается
# ни при одном ответе на соседний вопрос).
#
# Писать в невидимое опасно — там токены и служебные значения формы, — поэтому
# отбор двойной: сначала JS отдаёт ТОЛЬКО пустые `input[type=date]`, спрятанные
# и не заполненные, а решение по тексту блока принимает `wants_availability_date`
# на стороне Python, где его видно и можно проверить тестами.
_HIDDEN_DATES_JS = r"""() => {
  const out = [];
  document.querySelectorAll('input[type=date]').forEach((el, i) => {
    if (el.value) return;                       // уже заполнено — не трогаем
    if (el.offsetParent !== null) return;       // видимое разбирает обычный план
    const block = el.closest('.question, fieldset, .form-group, li, section')
                  || el.parentElement;
    out.push({i, text: ((block && block.innerText) || '').trim().slice(0, 200)});
  });
  return out;
}"""

# Значение ставим родным сеттером и шлём события: контролируемому полю
# (React/Turbo) присваивания через .value мало — стейт формы его не заметит.
_SET_DATE_JS = r"""([index, value]) => {
  const el = document.querySelectorAll('input[type=date]')[index];
  if (!el) return false;
  const setter = Object.getOwnPropertyDescriptor(
      window.HTMLInputElement.prototype, 'value').set;
  setter.call(el, value);
  el.dispatchEvent(new Event('input', {bubbles: true}));
  el.dispatchEvent(new Event('change', {bubbles: true}));
  return el.value === value;
}"""


def fill_hidden_required_dates(page, profile) -> list:
    """Проставить дату выхода в скрытые обязательные поля. Возвращает их подписи.

    Ничего не делает, когда таких полей нет или срок выхода в профиле разобрать
    не удалось: выдуманная дата ушла бы работодателю как обещание.
    """
    iso = availability_iso(getattr(profile, "notice_period", "") or "")
    if not iso:
        return []
    try:
        candidates = page.evaluate(_HIDDEN_DATES_JS)
    except Exception:  # noqa: BLE001 — фейковая страница/нет JS: молча мимо
        return []
    filled = []
    for c in candidates or []:
        text = (c or {}).get("text", "")
        if not wants_availability_date(text):
            continue
        try:
            if page.evaluate(_SET_DATE_JS, [c["i"], iso]):
                # innerText блока приходит с переносами и отступами вёрстки —
                # в лог человеку нужна одна строка.
                filled.append(" ".join(text.split())[:60])
        except Exception:  # noqa: BLE001 — одно поле не повод ронять заполнение
            continue
    return filled


def fill_and_submit(page, plan, dry_run: bool, profile=None) -> None:
    fill_fields(page, plan, profile=profile)
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


def _page_unavailable(page) -> bool:
    title = text = ""
    try:
        title = page.title() or ""
    except Exception:  # noqa: BLE001
        pass
    try:
        text = page.locator("body").inner_text(timeout=3000)[:4000]
    except Exception:  # noqa: BLE001
        pass
    return page_is_gone(title, text)


def _wants_cover_letter_file(obs) -> bool:
    """Есть ли на форме загрузка сопроводительного письма.

    Спрашиваем до сборки PDF: tectonic это отдельный процесс на несколько
    секунд, и запускать его на каждой форме, где такого поля нет, незачем.
    """
    return any(f.type == "file" and COVER_LETTER_RE.search(f"{f.label} {f.name}")
               for f in obs.fields)


# Длиннее этого список — уже не словарь поля, а СТРАНИЦА ответа сервера. Замер
# 2026-08-25: «School*» у Datadog отдаёт по открытию ровно 100 вузов по алфавиту
# от «3iL Limoges», остальные приходят по мере ввода; «Location (City)*» у N26 —
# ноль, там тоже ищет сервер. У настоящих словарей на тех же формах 1–30
# вариантов, и только «Country*» — 244, но на него отвечает профиль.
#
# Чего стоит спутать одно с другим: приняв сотню за словарь, мы отдаём её модели
# закрытым списком, а ответ на вопрос с вариантами клампится в индекс — «не
# знаю» там нет. Живой прогон 2026-08-25: выпускнику Astana IT University в
# анкету Datadog вписалось «Al-Farabi Kazakh National University». Ошибка в
# другую сторону дешёвая: вопрос остаётся свободным, модель отвечает по резюме,
# вариант ищет виджет, а не найдя — поле честно уходит в ручной отклик.
_VOCABULARY_LIMIT = 100


# Поля-справочники: список готовых названий, из которого форма ждёт выбора, а не
# сведения о самом кандидате. «employer», а не «employed» — намеренно: «Have you
# previously been employed with…» это вопрос про кандидата с ответом да/нет, и
# подменять его вариантом из списка нельзя.
_ROSTER_LABEL_RE = re.compile(
    r"school|universit|college|institut|education|alma mater|"
    r"employer|\bcompany\b|organi[sz]ation|"
    r"вуз|университет|учебн|образован|компани|работодател|организац",
    re.IGNORECASE)


# Регионы, которыми справочники подписывают вариант «моего тут нет». Замер
# 2026-08-25 на Datadog: на запрос «Other» приходят ровно шесть — Africa, Asia
# Pacific, Europe, Middle East, North America, South America. Виджет брал первый
# подходящий, то есть Африку, и выпускник из Астаны получал в анкету не тот
# континент. Формально это «вариант из списка», но верный лежит рядом.
#
# Список стран заведомо неполный и таким и задуман: он нужен, чтобы выбрать
# ЛУЧШИЙ из уже предложенных формой вариантов, а не чтобы знать географию. Не
# нашлось совпадения — берётся первый, как и было.
_REGION_HINTS = (
    ("asia pacific",
     r"kazakh|казах|uzbek|узбек|kyrgyz|киргиз|tajik|china|кита|india|инди|japan|"
     r"korea|коре|singapore|vietnam|thai|indonesia|malaysia|philippin|"
     r"australia|австрал|new zealand|hong kong|taiwan|asia|азия|азиат"),
    ("middle east",
     r"emirat|эмират|\buae\b|saudi|катар|qatar|kuwait|bahrain|oman|israel|"
     r"изра|jordan|lebanon|ливан"),
    ("europe",
     r"russia|росси|ukrain|укра|belarus|беларус|poland|польш|german|герман|"
     r"france|франц|spain|испан|italy|итал|nether|serbia|серб|georgia|груз|"
     r"armenia|армен|turkey|турц|portugal|португал|czech|чехи|sweden|norway|"
     r"finland|denmark|austria|австри|switzerland|швейцар|ireland|greece|"
     r"united kingdom|england|britain|британ|europe|европ"),
    ("north america",
     r"united states|\busa\b|\bu\.s\.|америк|canada|канад|mexico|мексик"),
    ("south america",
     r"brazil|бразил|argentin|аргентин|chile|чили|colomb|колумб|peru|перу|"
     r"uruguay|уругва|bolivia|ecuador|paraguay"),
    ("africa",
     r"nigeria|нигери|kenya|кени|egypt|егип|south africa|ghana|morocco|марокк|"
     r"tunisia|algeria|ethiopia|africa|африк"),
)


def _region_of(profile) -> str:
    """Название региона для страны из профиля, или "" если не узнали."""
    where = " ".join(str(getattr(profile, a, "") or "")
                     for a in ("country", "city", "location")).lower()
    if not where.strip():
        return ""
    for region, pattern in _REGION_HINTS:
        if re.search(pattern, where, re.IGNORECASE):
            return region
    return ""


def _roster_order(options, profile):
    """Варианты справочника в порядке предпочтения.

    Сначала «Other…» — форма держит его ровно для случая «моего тут нет», и это
    единственный по-настоящему верный ответ. Внутри «Other…» первым идёт
    подходящий регион. Всё остальное — после: это чужие названия, и брать их
    стоит только когда своего варианта форма не предложила вовсе.
    """
    region = _region_of(profile)
    other = [o for o in options if (o or "").strip().lower().startswith("other")]
    rest = [o for o in options if o not in other]
    if region:
        fitting = [o for o in other if region in (o or "").lower()]
        other = fitting + [o for o in other if o not in fitting]
    return other + rest


def _pick_any_from_roster(page, loc, field, profile=None) -> bool:
    """Взять из справочника ЛЮБОЙ вариант, когда своего в нём нет.

    Замер 2026-08-25 на форме Datadog (Greenhouse): «School*» ищет по серверу и
    на «Astana IT University» отдаёт ноль вариантов — как и на «Nazarbayev», а на
    «Kazakh» показывает семь чужих вузов. Нужного там нет и не будет: это
    справочник Greenhouse, а не перечень всех вузов мира. Поле обязательное, и
    из-за него не отправлялась вся заявка.

    Решение владельца профиля (2026-08-25): в выпадающем списке про учёбу или
    работодателя указывать любой вариант ИЗ СПИСКА, своё писать там, где поле
    свободное. Свободных полей это правило поэтому не касается вовсе — туда
    по-прежнему пишется настоящее значение.

    Порядок не случайный. Сначала «Other»: форма держит его ровно для случаев
    «моего тут нет», и это единственный по-настоящему верный ответ — у Datadog
    в справочнике лежит «Other - Asia Pacific». Первый попавшийся вариант
    берётся только когда «Other» списком не предложен.

    Ограничено справочниками намеренно. Для вопроса про визу, зарплату или
    готовность к переезду «любой вариант» — это неправда о себе, и там пустое
    поле с ручным откликом остаётся правильным исходом.
    """
    if not _ROSTER_LABEL_RE.search(f"{field.label} {field.name}"):
        return False
    # Порядок попыток. Справочник ищет по СЕРВЕРУ, и просто раскрытое меню
    # показывает первую сотню по алфавиту — у Datadog от «3iL Limoges», никаких
    # «Other» там нет. Они приходят только в ответ на ввод, и на «Other» их
    # шесть: Africa, Asia Pacific, Europe, Middle East, North America, South
    # America (замер 2026-08-25). Поэтому сначала спрашиваем СВОЙ регион целиком
    # — иначе вслепую набранное «Other» попадает в первый из шести, и выпускник
    # из Астаны получает в анкету Африку.
    region = _region_of(profile)
    if region and _fill_combobox(page, loc, f"Other - {region.title()}"):
        return True
    if _fill_combobox(page, loc, "Other"):
        return True
    try:
        options = _combobox_options(page, loc)
    except Exception:  # noqa: BLE001 — список не прочитался, значит выбирать не из чего
        return False
    for option in _roster_order(options, profile):
        if option and _fill_combobox(page, loc, option):
            return True
    return False


def _load_combobox_options(page, plan) -> None:
    """Достать варианты выпадающих вопросов и переспросить то, что мимо них.

    Скрапер приносит у combobox `options: []` — react-select держит варианты в
    попапе, и в DOM до открытия их нет. Отсюда две беды, обе замерены на живых
    формах, обе кончаются пустым обязательным полем:

    * модель отвечает вслепую, а поле принимает только своё — у N26 вопрос про
      GDPR берёт ровно «I Acknowledge», у Datadog аттестация — ровно «Yes»;
    * ответ ИЗ ПРОФИЛЯ мимо списка ничем не лучше. Прогон 2026-08-25: «Where are
      you currently based?*» получил «Astana, Kazakhstan», а список предлагает
      «Berlin / Vienna / Barcelona / Other»; «Start date month*» получил «1
      month» из срока выхода, а там названия месяцев. Оба поля остались пустыми,
      и обе формы ушли в ручной отклик, будучи заполненными на девять десятых.

    Поэтому список читается для КАЖДОГО выпадающего поля, а не только для тех,
    что идут к модели, и не подошедший к нему готовый ответ отправляется к ней
    же — теперь уже с вариантами перед глазами.

    Цена — одно открытие меню на поле, 0,65–1,74 с по замеру 2026-08-25 (N26:
    7,1 с на девять полей, Datadog: 16,5 с на двадцать пять, Profitap и
    BlueThrone: 0 с, выпадающих полей у них нет). Поэтому меню открывается
    только там, где без него не обойтись: варианты ещё не известны, поле
    выпадающее, и его вообще кто-то собирается заполнять.

    Само поле при чтении не заполняется: `combobox_options` только раскрывает
    список и закрывает его обратно, ничего не набирая.
    """
    for a in plan.actions:
        f = a.field
        # Необязательное поле без ответа из профиля и без задания модели
        # останется пустым в любом случае — на форме Datadog это, например,
        # «Are you Hispanic/Latino?». Открывать его меню незачем.
        if not f.combobox or f.options or not (a.needs_ai or a.value):
            continue
        try:
            options = list(
                _combobox_options(page, page.locator(f'[data-af="{f.ref}"]')))
        except Exception:  # noqa: BLE001 — без списка всё как было
            continue
        # Страницу сервера за словарь не выдаём: вопрос с вариантами клампится в
        # индекс, «не знаю» в таком ответе нет, и модель выбрала бы чужой вуз
        # из первой сотни по алфавиту. Свободным вопросом он отвечается по
        # резюме, а нужный вариант ищет уже виджет — он умеет печатать и ждать
        # ответа сервера. Пустой список — та же история, только явнее.
        if not options or len(options) >= _VOCABULARY_LIMIT:
            continue
        f.options = options
        # Совпадение проверяет ТОТ ЖЕ `_best`, которым виджет будет выбирать
        # вариант. Готовый `_option_index_for` из auto_apply здесь не годится:
        # он ищет вхождение в обе стороны без границы слова, и на живом списке
        # месяцев ответ «No» считает ноябрём (проверено 2026-08-25) — поле
        # осталось бы с ответом, который виджет всё равно не выберет. Решать
        # должна одна функция, иначе проверка и нажатие расходятся.
        if not a.value or _best(options, a.value) is not None:
            continue
        # «Prefer not to say» — не догадка профиля, а решение не отвечать, и в
        # чужом словаре оно называется иначе: у Datadog это «Decline To Self
        # Identify», «I don't wish to answer», «I do not want to answer».
        # Спрашивать про такое модель значит просить её ответить по существу —
        # резюме она читала, и имя в нём есть. Выбираем то же, что выбрал бы
        # map_field, знай он варианты при разборе формы.
        if a.source == "eeo":
            idx = _match_choice(options, "prefer not", "decline", "not to say")
            a.choice_index = len(options) - 1 if idx is None else idx
            a.value = options[a.choice_index]
            continue
        # Готовый ответ, которого нет в списке, — это пустое поле. Пусть его
        # выберет модель: варианты у неё теперь есть, а профиль про чужой
        # словарь знать не обязан.
        a.value = ""
        a.choice_index = None
        a.needs_ai = True
        a.source = "ai"


def _hop_to_embedded_form(page, obs, route):
    """Последняя попытка перед ручным откликом: перейти на форму вендора.

    Careers-страница компании ставит у себя скрипт ATS, а форму он подтягивает
    отдельным запросом — и иногда в DOM её так и не вставляет. Замер 2026-08-24
    на вакансии Datadog из Remocate: ноль полей, ноль iframe, ни одной кнопки
    «Apply», то есть `_reveal_apply_form` кликать нечего и маршрут выходит NONE.
    При этом страница сама ходит за формой на job-boards.greenhouse.io, а тот же
    адрес открытым текстом отдаёт 60 полей и загрузку файла.

    Стоит последней: сначала пробуем то, что уже работает, и только на пустой
    странице тратим ещё одну навигацию. Возвращает прежние (obs, route), если
    адрес не собрался или переход ничего не дал — тогда всё идёт как раньше, в
    ручной отклик.
    """
    try:
        url = greenhouse_embed_url(page.content(), page.url)
    except Exception:  # noqa: BLE001 — не смогли прочитать страницу, не повод падать
        return obs, route
    if not url:
        # Вендор кладёт форму рядом со страницей вакансии: у Teamtailor это
        # `…/applications/new`, у Recruitee `…/c/new`. Кто вендор — решает
        # делегирование в DNS, а не вёрстка, поэтому спрашиваем apply_guard.
        # Замер 2026-08-24: у careers.bluethrone.io кнопка подписана «Join us»,
        # под селектор раскрытия не попадает, и без этого перехода форма из 19
        # полей оставалась недостижимой.
        url = vendor_apply_url(page.url, vendor_behind(page.url))
    if not url:
        return obs, route
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(_EMBED_SETTLE_MS)
        return scrape_until_ready(page)
    except Exception:  # noqa: BLE001 — переход не удался: остаёмся на прежнем ответе
        return obs, route


def external_apply(page, job_url: str, content, profile, cv_path: str,
                   answerer=None, dry_run: bool = False, email_channel=None,
                   subject_maker=None, vacancy_context: str = "") -> None:
    obs, route = scrape_until_ready(page)
    if route is Route.NONE and _reveal_apply_form(page):
        # Кнопка «Apply» ведёт к форме не всегда. Замер 2026-08-26 на Zalando
        # (лиды #412, #413): там Usercentrics, согласие нарисовано в shadow DOM,
        # мы его не видим и не отвечаем — и кнопка уводит на текст политики
        # обработки данных, где ни формы, ни продолжения нет.
        #
        # Раньше в таблицу уходило «форма не распознана: <адрес политики>» —
        # формально правда, но это ложный след: выглядит как поломка разбора
        # формы. Говорим прямо и показываем адрес ВАКАНСИИ, а не документа, —
        # откликаться человек пойдёт туда.
        if looks_like_legal_page(getattr(page, "url", "")):
            raise ManualApplyRequired(
                "кнопка отклика увела на юридический текст (похоже, сайт ждёт "
                f"ответа на согласие), формы там нет — отклик руками: {job_url}")
        obs, route = scrape_until_ready(page)   # form opened in a modal / next step
    if route is Route.NONE:
        obs, route = _hop_to_embedded_form(page, obs, route)

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
            raise ManualApplyRequired(f"{GONE_NOTE}: {obs.url}")
        raise ManualApplyRequired(f"форма не распознана: {obs.url}")

    # Checked here, on the page that actually holds the form — not on job_url.
    # An IFRAME_ATS lands on a company page but fills the vendor's form (obs.url is
    # the vendor after _enter_ats_iframe), and the EMAIL route returns above without
    # filling anything. Only a form we are about to fill and submit needs the host
    # to be one we recognise: the page supplies the labels that reach the model and
    # receives whatever it answers.
    # Не только хост, но и вендор за ним: компания вешает ATS на свой домен, и
    # `jobs.profitap.com` это Recruitee, а `careers.bluethrone.io` — Teamtailor,
    # оба из списка (замер 2026-08-24, оба ушли в ручной отклик). Доказывает это
    # делегирование в DNS, а не вёрстка — см. apply_guard. Сетевой запрос уходит
    # ТОЛЬКО когда хост не в списке; на greenhouse и linkedin он бесплатный.
    if not host_or_vendor_allowed(obs.url):
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
    _load_combobox_options(page, plan)
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
    fill_and_submit(page, plan, dry_run, profile=profile)
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
