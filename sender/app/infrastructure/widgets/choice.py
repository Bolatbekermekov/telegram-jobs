"""Ответ на вопрос с вариантами — и доказательство, что ответ принят.

Зачем отдельный модуль. Замер живой формы Recruitee 2026-08-24
(jobs.profitap.com/o/qa-engineer-3/c/new, лид #418) показал, что настоящие
`input[type=radio]` там есть и скрапер видит их правильно — один вопрос
«Do you require visa sponsorship? *», options ["Yes","No"], required. Спрятаны
они классическим «visually hidden»:

    position:absolute; width:1px; height:1px; clip:rect(0px,0px,0px,0px);
    margin:-1px; padding:0; border:0; overflow:hidden; white-space:nowrap

а видимая кнопка — это `<label for=…>` с двумя span-ами рядом.

`fill_fields` жмёт по такой кнопке `check(force=True)`, то есть настоящий клик
мышью в центр прямоугольника 1×1 с `clip: rect(0,0,0,0)`. `elementFromPoint` в
этой точке возвращает null, и в HEADED Chrome клик до кнопки не доходит:

    Locator.check: Clicking the checkbox did not change its state
      - scrolling into view if needed / done scrolling
      - forcing action / performing click action / click action done

Дальше по цепочке: исключение → поле обязательное → ManualApplyRequired
«не смог заполнить обязательное поле». В headless тот же вызов проходит, поэтому
ни один тест этого не ловил, а прогон идёт headed — `BROWSER_HEADLESS` по
умолчанию `false`.

Отдельно замерено, что «починка» кликом была бы хуже болезни: `click(force=True)`
на той же кнопке НЕ бросает ничего и НЕ выбирает ничего — вопрос молча остался
бы без ответа, а заявка ушла бы.

Что работает. Нативный `el.click()` — тот же приём, которым в `fill_and_submit`
жмётся «Submit»: он не ищет точку попадания, поэтому ему всё равно, что кнопка
1×1, накрыта оверлеем или лежит в `display:none`. Замер по вариантам разметки
(headless, 2026-08-24):

    разметка                 check(force=True)                     el.click()
    clip 1px (Recruitee)     OK headless / «did not change» headed  OK
    position:absolute -9999  «Element is outside of the viewport»   OK
    width:0;height:0         «Element is outside of the viewport»   OK
    оверлей поверх           «Clicking … did not change its state»  OK
    родитель display:none    «Element is not visible»               OK

Чем доказывается, что ответ принят. Не тем, что вызов не бросил исключение, —
этому уже научила заявка без резюме (Ashby, лид 123). Читается СОСТОЯНИЕ
контрола (`checked`, для ARIA-виджета `aria-checked`) и, если контрол лежит в
`<form>` и у него есть `name`, ещё и `new FormData(form)` — то, что реально
уедет работодателю. На той же форме Recruitee до ответа записи
`candidate.openQuestionAnswers.6703065.flag` в FormData нет вовсе, после клика
по метке появляется `"false"`, и она переживает перерисовку React.

Чем НЕ доказывается. Тем, что наша собственная пометка на узле пережила клик.
Живьём 2026-09-03 (лид #800, LinkedIn Easy Apply, «Will you now or in the future
require sponsorship…»): в сохранённой странице «No» стоит `checked`, у его
обёртки появился `componentkey="auto-component-…"`, которого нет у соседней, —
React заменил ровно ту ветку, по которой пришёл клик. Пометка живёт на СТАРОМ
узле и в документ уже не входит, поэтому проверка не нашла ничего, а оба клика
мышью следом отвалились по таймауту 3 с (`[data-af-pick=…]` не находит
заменённый узел). Отчёт сказал «клик прошёл, но страница ответ не засчитала» —
и лид ушёл в ручные при ПРИНЯТОМ ответе. Это тот же обман, что и «отклик не
подтверждён» на hh, и цена та же: человек делает вручную уже сделанное.

Поэтому вариант переискивается ЗАНОВО, тремя опорами по убыванию надёжности:
имя группы плюс номер среди кнопок с этим именем; `id`; подпись вопроса плюс
номер варианта внутри её блока. Три, а не одна, потому что каждая из первых
двух живьём отказала: у одиночной галочки «I consent» имени нет вовсе, а на
втором заходе (тот же лид, тот же вопрос) блок не перерисовался, а
ПЕРЕМОНТИРОВАЛСЯ — новый компонент получил новый `useId`, и прежний id тоже
перестал что-либо находить. Подпись вопроса пережила и это.

Сравниваются первые 60 знаков подписи, а не вся: форма дописывает в тот же блок
текст ошибки, и точное равенство отказало бы ровно тогда, когда переиск нужнее
всего. Пометка осталась последним запасным путём — для вариантов, нарисованных
div-ами без единого `input`, где переискать не по чему.

Наружу исключения не выходят: вызывающая сторона получает False и сама решает,
что это значит для обязательного поля.
"""

# Клик мышью по метке и `check(force=True)` — запасные пути, каждый со своим
# ожиданием. 3 секунды: накрытая оверсеем метка иначе съедает по 8 секунд на
# каждый вопрос, а всё, что реально работает, срабатывает мгновенно.
_CLICK_TIMEOUT_MS = 3000
# Сколько ждать сам контрол. Форму могло перерисовать между планом и
# заполнением; ждать 30 секунд (умолчание Playwright) незачем — цена ошибки тут
# это одно поле, а не прогон.
_RESOLVE_TIMEOUT_MS = 2000

# Общая часть всех вычислений на странице. `labelFor` и способ собрать группу —
# ЗЕРКАЛО `_SCRAPE_JS`: план хранит номер варианта из его `options`, и если
# считать группу иначе, номер укажет на чужую кнопку.
_HELPERS = r"""
  const norm = s => (s||'').replace(/\s+/g,' ').trim().slice(0,80);
  const clean = s => norm(s).toLowerCase();
  const labelFor = el => {
    if (el.getAttribute('aria-label')) return norm(el.getAttribute('aria-label'));
    if (el.id) { const l = document.querySelector('label[for="'+el.id+'"]'); if (l) return norm(l.textContent); }
    const l2 = el.closest('label'); if (l2) return norm(l2.textContent);
    if (el.placeholder) return norm(el.placeholder);
    return norm(el.name || el.textContent);
  };
  // Метка, по которой можно кликнуть. Ashby выдаёт ВСЕМ кнопкам группы один и
  // тот же id, поэтому `label[for=…]` там указывает не на ту кнопку; такая
  // метка отбрасывается, а не жмётся наугад.
  const ownLabel = el => {
    const inside = el.closest && el.closest('label');
    if (inside) return inside;
    if (el.id && document.getElementById(el.id) === el) {
      const ls = [...document.querySelectorAll('label[for="'+el.id+'"]')];
      if (ls.length === 1) return ls[0];
    }
    return null;
  };
  const role = el => (el.getAttribute && el.getAttribute('role') || '').toLowerCase();
  const groupOf = el => {
    const t = (el.type || '').toLowerCase();
    if ((t === 'radio' || t === 'checkbox') && el.name) {
      const g = [...document.querySelectorAll('input[type=' + t + ']')]
                  .filter(r => r.name === el.name);
      if (g.length) return g;
    }
    // Варианты, нарисованные без настоящего input: выбор виден по aria-checked.
    if (/^(radio|option|menuitemradio|checkbox)$/.test(role(el))) {
      const box = el.closest('[role=radiogroup],[role=listbox],[role=group],fieldset');
      const g = box ? [...box.querySelectorAll('[role=' + role(el) + ']')] : [];
      if (g.length) return g;
    }
    const box = el.closest && el.closest('fieldset,[role=radiogroup],[role=group]');
    if (box && t) {
      const g = [...box.querySelectorAll('input[type=' + t + ']')];
      if (g.length) return g;
    }
    return [el];
  };
  const isPicked = el => typeof el.checked === 'boolean'
    ? el.checked
    : (el.getAttribute && el.getAttribute('aria-checked') === 'true');
  // Попал ли ответ в ДАННЫЕ формы. null = проверить нечем (контрол вне <form>
  // или без имени) — тогда судим по состоянию контрола.
  const inFormData = el => {
    const f = el.form || (el.closest && el.closest('form'));
    if (!f || !el.name) return null;
    try {
      for (const [k, v] of new FormData(f)) if (k === el.name && v === el.value) return true;
    } catch (e) { return null; }
    return false;
  };
  const accepted = el => isPicked(el) && inFormData(el) !== false;
  // Как найти ТОТ ЖЕ вариант ЗАНОВО, если наш узел заменили. Атрибут-метка это
  // не переживает: она живёт на узле, а React после клика подставляет новый.
  // Имя группы переживает — это `useId` компонента, оно одно и то же до и после
  // перерисовки.
  const sameName = (t, n) => [...document.querySelectorAll('input[type=' + t + ']')]
                               .filter(r => r.name === n);
  // Текст вопроса целиком — последняя опора, когда не пережили ни имя, ни id.
  const deepNorm = s => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  // Блок вопроса: LinkedIn держит подпись СОСЕДОМ `fieldset`, поэтому берётся
  // родитель, а не сам `fieldset` — иначе текстом группы будет «yes no», и на
  // форме с двумя вопросами Yes/No он укажет не на тот.
  const blockOf = el => {
    const fs = el.closest && el.closest('fieldset,[role=radiogroup],[role=group]');
    if (fs) return fs.parentElement || fs;
    return (el.closest && el.closest('label')) || el.parentElement;
  };
  // Сравниваются первые 60 знаков: страница дописывает в блок текст ошибки
  // («Select checkbox to proceed»), и точное равенство сломалось бы ровно
  // тогда, когда переиск нужнее всего. Подпись вопроса стоит первой.
  const blockKey = n => deepNorm(n && n.textContent).slice(0, 60);
  const keyOf = el => {
    const t = (el.type || '').toLowerCase();
    const k = {type: t};
    if ((t === 'radio' || t === 'checkbox') && el.name) {
      const i = sameName(t, el.name).indexOf(el);
      if (i >= 0) { k.name = el.name; k.nameIndex = i; }
    }
    if (el.id) k.id = el.id;
    const b = blockOf(el);
    if (b && t) {
      const i = [...b.querySelectorAll('input[type=' + t + ']')].indexOf(el);
      if (i >= 0) { k.block = blockKey(b); k.blockIndex = i; }
    }
    return k;
  };
  const byKey = k => {
    if (!k) return null;
    if (k.name) {
      const g = sameName(k.type, k.name);
      if (g[k.nameIndex]) return g[k.nameIndex];
    }
    // Сравнением, а не селектором: id вида «r36» содержит кавычки-ёлочки, и
    // подставлять такое в CSS — напрашиваться на SyntaxError вместо элемента.
    if (k.id) {
      const e = [...document.querySelectorAll('[id]')].find(x => x.id === k.id);
      if (e) return e;
    }
    // Перемонтирование: живьём 2026-09-03 (лид #805) у новой галочки не было
    // ни `data-af`, ни прежнего id — React выдал новый `useId`. Пережил только
    // текст вопроса, и номер варианта внутри его блока.
    if (k.block) {
      const boxes = [...document.querySelectorAll(
        'fieldset,[role=radiogroup],[role=group]')].map(f => f.parentElement || f);
      for (const b of boxes) {
        if (blockKey(b) !== k.block) continue;
        const g = [...b.querySelectorAll('input[type=' + k.type + ']')];
        if (g[k.blockIndex]) return g[k.blockIndex];
      }
    }
    return null;
  };
  // Ключ главнее метки: метка могла остаться на узле, который уже выброшен из
  // документа, а ключ всегда указывает на живой.
  const find = k => byKey(k) || document.querySelector('[data-af-pick="1"]') || null;
"""

# Найти нужный вариант, пометить его и рассказать, что с ним. Пометка своя
# (`data-af-pick`), а не `data-af` скрапера: тот принадлежит снимку формы, и
# затирать его здесь нельзя.
_RESOLVE_JS = _HELPERS + r"""
  const el = arguments[0], want = arguments[1];
  document.querySelectorAll('[data-af-pick],[data-af-pick-label]').forEach(
    e => { e.removeAttribute('data-af-pick'); e.removeAttribute('data-af-pick-label'); });
  const g = groupOf(el);
  let i = want.index;
  if (!(i >= 0 && i < g.length)) {
    const w = clean(want.value);
    if (!w) return {found: false};
    const texts = g.map(labelFor).map(clean);
    i = texts.indexOf(w);
    // Значение атрибута — второй заход: Recruitee пишет в него "true"/"false",
    // а подписи у кнопок "Yes"/"No".
    if (i < 0) i = g.map(e => clean(e.value)).indexOf(w);
    // И только потом — целым словом. Подстрокой нельзя: «No» лежит внутри
    // «Not sure» и «No experience with React», и ответ вышел бы не тем, что
    // решил план, а сказать об этом было бы некому.
    if (i < 0) {
      const re = new RegExp('(^|\\W)' + w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '($|\\W)');
      i = texts.findIndex(t => re.test(t));
    }
  }
  if (!(i >= 0 && i < g.length)) return {found: false};
  const target = g[i];
  target.setAttribute('data-af-pick', '1');
  const lab = ownLabel(target);
  if (lab) lab.setAttribute('data-af-pick-label', '1');
  return {found: true, disabled: !!target.disabled, accepted: accepted(target),
          label: labelFor(target), has_label: !!lab, key: keyOf(target)};
"""

_STATE_JS = _HELPERS + r"""
  const el = find(arguments[0]);
  return el ? {found: true, accepted: accepted(el)} : {found: false};
"""

# Поставить метку заново на живой узел. Нужна кликам мышью: они ходят по CSS
# `[data-af-pick=…]`, и после перерисовки этот селектор не находит ничего —
# оба способа съедали по 3 секунды таймаута и сообщали не о том.
_RESTAMP_JS = _HELPERS + r"""
  const el = find(arguments[0]);
  if (!el) return {found: false};
  document.querySelectorAll('[data-af-pick],[data-af-pick-label]').forEach(
    e => { e.removeAttribute('data-af-pick'); e.removeAttribute('data-af-pick-label'); });
  el.setAttribute('data-af-pick', '1');
  const lab = ownLabel(el);
  if (lab) lab.setAttribute('data-af-pick-label', '1');
  return {found: true, has_label: !!lab};
"""

# Нативный клик: событие настоящее для страницы (React его видит и обновляет
# своё состояние), но точка попадания не нужна — поэтому спрятанная,
# накрытая или не разложенная кнопка ему не помеха.
# Возвращает, НАШЁЛСЯ ли помеченный элемент. Без этого «native_click» в отчёте
# значил и «кликнули, страница не приняла», и «кликать было уже не по чему»:
# `el.click()` при null не бросает ничего. Живьём 2026-09-01 на LinkedIn Easy
# Apply оба локатора Playwright после него отваливались по таймауту — а это
# ровно то, что бывает, когда метку снял перерисовавший форму React.
_NATIVE_CLICK_JS = _HELPERS + r"""
  const el = find(arguments[0]);
  if (!el) return {found: false};
  el.click();
  return {found: true};
"""

_UNSTAMP_JS = r"""() => document.querySelectorAll('[data-af-pick],[data-af-pick-label]')
  .forEach(e => { e.removeAttribute('data-af-pick'); e.removeAttribute('data-af-pick-label'); });
"""


def _fn(body: str) -> str:
    """JS-выражение из тела: Playwright ждёт функцию, а `arguments` внутри
    стрелочной не работает — поэтому обычная."""
    return "function () {\n" + body + "\n}"


def pick_choice(page, locator, value: str = "", index: int | None = None) -> bool:
    """Совместимая обёртка: True/False без причины. Причина — в pick_choice_reason."""
    return pick_choice_reason(page, locator, value, index)[0]


def pick_choice_reason(page, locator, value: str = "",
                       index: int | None = None) -> tuple[bool, str]:
    """Выбрать вариант ответа. True — только если выбор ПОДТВЕРЖДЁН страницей.

    `locator` — контрол, найденный скрапером (он метит их `data-af=<индекс>`);
    для группы это её первая кнопка. `index` — номер варианта в `options` того
    же скрапера, `value` — его подпись; номер главнее, подпись работает, когда
    номера нет (`_yes_no` возвращает голое «No», если вариантов не нашлось).

    Годится для radio, для группы чекбоксов и для вариантов, нарисованных без
    настоящего input (`role=radio` + `aria-checked`). Выпадающий список сюда не
    относится: у `<select>` есть свой `select_option`.

    False — это честный отказ («страница ответ не приняла»), а не поломка:
    исключения наружу не выходят, потому что для обязательного поля решение
    принимает вызывающая сторона, и её собственный диагноз затирать нельзя.

    Вторым значением возвращается ПРИЧИНА отказа. Без неё заметка лида говорила
    только «не выбрался вариант «Yes»», а за этим стоят четыре разных случая, и
    чинятся они по-разному: варианта нет в группе, контрол выключен страницей,
    контрол не найден вовсе (форму перерисовало), или все три способа клика
    отработали, а страница ответ так и не засчитала. Живьём 2026-08-29 этот
    отказ пришёл ЧЕТЫРЕ раза за один прогон на LinkedIn Easy Apply («Do you have
    experience with GO?», «valid driver's license», «comfortable commuting»), и
    разобрать его было нечем.
    """
    try:
        found = locator.first.evaluate(
            _fn(_RESOLVE_JS),
            {"value": value or "", "index": -1 if index is None else int(index)},
            timeout=_RESOLVE_TIMEOUT_MS)
    except Exception as exc:  # noqa: BLE001 — контрола нет / страница перерисовалась
        return (False, f"контрол не найден: {str(exc)[:70]}")
    if not isinstance(found, dict) or not found.get("found"):
        return (False, "варианта нет среди кнопок группы")
    # Выключенный контрол в данные формы не попадает, сколько по нему ни бей —
    # и трогать его незачем: страница сама сказала, что ответ тут не берут.
    if found.get("disabled"):
        _unstamp(page)
        return (False, f"страница держит вариант «{found.get('label') or ''}» выключенным")
    if found.get("accepted"):
        # Уже выбран. Для ЧЕКБОКСА повторный клик снял бы галочку, то есть
        # ответ на противоположный, поэтому выходим до всяких кликов.
        _unstamp(page)
        return (True, "")
    key = found.get("key")
    try:
        tried = []
        for attempt in (_native_click, _label_click, _force_check):
            name = attempt.__name__.strip("_")
            if attempt is _label_click and not found.get("has_label"):
                tried.append(f"{name}: метки нет")
                continue
            try:
                attempt(page, found, key)
                tried.append(name)
            except Exception as exc:  # noqa: BLE001 — следующий способ важнее причины
                tried.append(f"{name}: {str(exc).splitlines()[0][:50]}")
            if _accepted(page, key):
                return (True, "")
        return (False, "клик прошёл, но страница ответ не засчитала — " + "; ".join(tried))
    finally:
        _unstamp(page)


def _native_click(page, found, key=None) -> None:
    res = page.evaluate(_fn(_NATIVE_CLICK_JS), key)
    if isinstance(res, dict) and not res.get("found"):
        raise RuntimeError("метка не дожила до клика (страницу перерисовало?)")


def _label_click(page, found, key=None) -> None:
    """Клик мышью по видимой метке — путь человека. Нужен там, где страница
    смотрит на `event.isTrusted` и нативный клик ей не годится."""
    if not found.get("has_label"):
        return
    if not _restamp(page, key):
        raise RuntimeError("метка не дожила до клика (страницу перерисовало?)")
    page.locator('[data-af-pick-label="1"]').first.click(timeout=_CLICK_TIMEOUT_MS)


def _force_check(page, found, key=None) -> None:
    """Ровно то, что делает `fill_fields` сегодня. Остаётся последним: на живой
    Recruitee в headed он и не сработал, но на разметке, где страница ждёт
    настоящий ввод именно в контрол, он единственный подходит."""
    if not _restamp(page, key):
        raise RuntimeError("метка не дожила до клика (страницу перерисовало?)")
    page.locator('[data-af-pick="1"]').first.check(force=True, timeout=_CLICK_TIMEOUT_MS)


def _restamp(page, key) -> bool:
    """Вернуть метку на живой узел перед кликом мышью. False — вариант исчез и
    по имени группы не нашёлся; тогда кликать не по чему и ждать таймаут незачем."""
    try:
        res = page.evaluate(_fn(_RESTAMP_JS), key)
    except Exception:  # noqa: BLE001
        return False
    return bool(isinstance(res, dict) and res.get("found"))


def _accepted(page, key=None) -> bool:
    try:
        state = page.evaluate(_fn(_STATE_JS), key)
    except Exception:  # noqa: BLE001
        return False
    return bool(isinstance(state, dict) and state.get("accepted"))


def _unstamp(page) -> None:
    try:
        page.evaluate(_UNSTAMP_JS)
    except Exception:  # noqa: BLE001 — метка на чужой странице, убрать не вышло
        pass
