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
  const find = () => {
    const stamped = document.querySelector('[data-af-pick="1"]');
    if (stamped) return stamped;
    return null;
  };
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
          label: labelFor(target), has_label: !!lab};
"""

_STATE_JS = _HELPERS + r"""
  const el = find();
  return el ? {found: true, accepted: accepted(el)} : {found: false};
"""

# Нативный клик: событие настоящее для страницы (React его видит и обновляет
# своё состояние), но точка попадания не нужна — поэтому спрятанная,
# накрытая или не разложенная кнопка ему не помеха.
_NATIVE_CLICK_JS = _HELPERS + r"""
  const el = find();
  if (el) el.click();
"""

_UNSTAMP_JS = r"""() => document.querySelectorAll('[data-af-pick],[data-af-pick-label]')
  .forEach(e => { e.removeAttribute('data-af-pick'); e.removeAttribute('data-af-pick-label'); });
"""


def _fn(body: str) -> str:
    """JS-выражение из тела: Playwright ждёт функцию, а `arguments` внутри
    стрелочной не работает — поэтому обычная."""
    return "function () {\n" + body + "\n}"


def pick_choice(page, locator, value: str = "", index: int | None = None) -> bool:
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
    """
    try:
        found = locator.first.evaluate(
            _fn(_RESOLVE_JS),
            {"value": value or "", "index": -1 if index is None else int(index)},
            timeout=_RESOLVE_TIMEOUT_MS)
    except Exception:  # noqa: BLE001 — контрола нет / страница перерисовалась
        return False
    if not isinstance(found, dict) or not found.get("found"):
        return False
    # Выключенный контрол в данные формы не попадает, сколько по нему ни бей —
    # и трогать его незачем: страница сама сказала, что ответ тут не берут.
    if found.get("disabled"):
        _unstamp(page)
        return False
    if found.get("accepted"):
        # Уже выбран. Для ЧЕКБОКСА повторный клик снял бы галочку, то есть
        # ответ на противоположный, поэтому выходим до всяких кликов.
        _unstamp(page)
        return True
    try:
        for attempt in (_native_click, _label_click, _force_check):
            try:
                attempt(page, found)
            except Exception:  # noqa: BLE001 — следующий способ важнее причины
                pass
            if _accepted(page):
                return True
        return False
    finally:
        _unstamp(page)


def _native_click(page, found) -> None:
    page.evaluate(_fn(_NATIVE_CLICK_JS))


def _label_click(page, found) -> None:
    """Клик мышью по видимой метке — путь человека. Нужен там, где страница
    смотрит на `event.isTrusted` и нативный клик ей не годится."""
    if not found.get("has_label"):
        return
    page.locator('[data-af-pick-label="1"]').first.click(timeout=_CLICK_TIMEOUT_MS)


def _force_check(page, found) -> None:
    """Ровно то, что делает `fill_fields` сегодня. Остаётся последним: на живой
    Recruitee в headed он и не сработал, но на разметке, где страница ждёт
    настоящий ввод именно в контрол, он единственный подходит."""
    page.locator('[data-af-pick="1"]').first.check(force=True, timeout=_CLICK_TIMEOUT_MS)


def _accepted(page) -> bool:
    try:
        state = page.evaluate(_fn(_STATE_JS))
    except Exception:  # noqa: BLE001
        return False
    return bool(isinstance(state, dict) and state.get("accepted"))


def _unstamp(page) -> None:
    try:
        page.evaluate(_UNSTAMP_JS)
    except Exception:  # noqa: BLE001 — метка на чужой странице, убрать не вышло
        pass
