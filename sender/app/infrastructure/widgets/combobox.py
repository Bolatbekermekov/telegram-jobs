"""Выпадающее поле, которое выглядит текстовым: выбрать вариант из ЕГО списка.

Зачем отдельный модуль. Прогон 2026-08-24 встал на двух живых формах Greenhouse:
«внешняя форма: не смог заполнить обязательное поле «Location (City)*»» (N26,
`job_app?for=n26&token=7925103`) и то же самое на «School*» (Datadog,
`?for=datadog&token=8052095`). Оба поля — react-select:

    <div class="select__input-container" data-value="">
      <input class="select__input" id="candidate-location" role="combobox"
             aria-autocomplete="list" aria-expanded="false" aria-required="true">
    </div>
    …
    <input required tabindex="-1" aria-hidden="true" class="…-requiredInput" value="">

Что показал замер 2026-08-24 (по шагам, живьём):

* до открытия вариантов в DOM НЕТ ни одного, и `aria-controls` у поля тоже нет;
* по клику поле получает `aria-controls="react-select-<id>-listbox"`, а внутри
  `.select-shell` появляется `div.select__menu > [role=listbox] > div[role=option]`;
* статический список («Degree», месяцы, «Yes/No») готов через ~400 мс; список,
  который тянется с сервера, — позже: у N26 варианты «Location (City)» пришли
  между 1.2 и 2.7 секунды ПОСЛЕ ввода, и всё это время в меню видны варианты
  предыдущего запроса (у Datadog «School» это первая сотня вузов по алфавиту);
* фильтр — по подстроке, без снисхождения к пунктуации: «Bachelors Degree» не
  находит НИЧЕГО, «Bachelor» находит «Bachelor's Degree»;
* после выбора: меню исчезает, `aria-controls` снимается, ввод очищается
  (`input.value === ''`), плейсхолдер заменяется на `div.select__single-value`,
  а служебный `<input required aria-hidden>` удаляется из DOM.

Почему прежний `_fill_typeahead` не мог справиться. Он искал варианты по ВСЕЙ
странице (`page.locator("[role=option]").first`). На каждой форме Greenhouse
рядом с полем «Phone» живёт intl-tel-input, и его список из 244 стран лежит в
DOM с загрузки страницы, скрытый классом `iti__hide`. Первым `[role=option]`
всегда оказывался `iti-0__item-af` — «Afghanistan +93». Клик уходил в скрытый
элемент, ждал видимости до таймаута и падал, а обязательное поле объявлялось
незаполненным. Плюс фиксированные 1500 мс ожидания попадали ровно в промежуток,
когда своих вариантов ещё нет, а чужие уже есть.

Отсюда правила этого модуля: список ищется только внутри СВОЕГО виджета (по
`aria-controls`/`aria-owns` или в корне виджета), скрытые варианты не в счёт,
ждём не время, а ПОЯВЛЕНИЕ подходящего варианта, и жмём вариант, который
совпал с ответом, а не тот, что оказался первым.
"""
import re
import time

# Шаг опроса меню. Реже — теряем секунды на каждом поле, чаще — молотим страницу
# впустую: перерисовка списка у react-select занимает десятки миллисекунд.
_POLL_MS = 200
# Сколько ждать список, который рисуется без ввода (статический). Замер: ~400 мс.
_OPEN_BUDGET_MS = 1500
# Сколько ждать ответ сервера после ввода. Замер на N26: до 2.7 с; берём с запасом.
_TYPED_BUDGET_MS = 3500
# Сколько список должен не меняться, чтобы счесть его окончательным. Пустой так
# не считается: у N26 меню «Location (City)» стоит пустым до 2.5 секунды, пока
# идёт запрос, и «пусто уже полсекунды» там значит только «ещё не пришло».
_SETTLE_MS = 600
# Ожидания самих действий. Ждать по 30 секунд (умолчание Playwright) незачем:
# цена ошибки тут — одно поле, а не прогон.
_CLICK_TIMEOUT_MS = 4000
_ACT_TIMEOUT_MS = 2000
# Общий потолок на поле: четыре запроса подряд по 3.5 с в него не влезут — и не
# должны, иначе анкета с двумя десятками выпадающих полей растянется на минуты.
# Замер живьём 2026-08-24: попадание стоит 0.1–2.6 с, промах — до 9 с.
TOTAL_TIMEOUT_MS = 15000

_HELPERS = r"""
  const norm = s => (s||'').replace(/\s+/g,' ').trim();
  // Скрытый вариант — не вариант. Именно этим отсекается список стран
  // intl-tel-input: он лежит в DOM всегда, но под `display:none`.
  const visible = e => e.getClientRects().length > 0
    && getComputedStyle(e).visibility !== 'hidden';
  // Корень виджета — самый верхний предок, в котором всё ещё ровно один
  // combobox, наш. Выше начинаются соседние вопросы (у Datadog School, Degree и
  // обе даты лежат в одной строке), и всё, что мы там найдём, будет чужим.
  const rootOf = el => {
    let best = el.parentElement || el;
    for (let n = best; n && n !== document.documentElement; n = n.parentElement) {
      if (n.querySelectorAll('[role=combobox]').length > 1) break;
      best = n;
    }
    return best;
  };
  const optionsIn = m => m ? [...m.querySelectorAll('[role=option]')].filter(visible) : [];
  // Список ИМЕННО этого поля. `aria-controls` react-select проставляет на время,
  // пока меню открыто (у LinkedIn то же самое зовётся `aria-owns`), и это
  // единственная связь, которая работает, когда меню вынесено в конец body.
  const menuOf = el => {
    const id = el.getAttribute('aria-controls') || el.getAttribute('aria-owns');
    const byId = id ? document.getElementById(id) : null;
    if (byId) return byId;
    const root = rootOf(el);
    const lb = [...root.querySelectorAll('[role=listbox]')].find(l => optionsIn(l).length);
    if (lb) return lb;
    return optionsIn(root).length ? root : null;
  };
  // Выбранное значение так, как его хранит react-select: отдельным узлом рядом с
  // полем, а не в самом поле. Вложенные узлы («…multi-value-label» внутри
  // «…multi-value») отбрасываются, иначе один ответ посчитается дважды.
  const VALUE_SEL = '[class*=singleValue],[class*=single-value],'
                  + '[class*=multiValue],[class*=multi-value]';
  const shownIn = root => [...root.querySelectorAll(VALUE_SEL)]
    .filter(n => !(n.parentElement && n.parentElement.closest(VALUE_SEL)))
    .map(n => norm(n.innerText)).filter(Boolean).join(', ');
  // Тот самый безымянный вход, которым Greenhouse заставляет браузер ругаться на
  // пустой выбор. Пока выбора нет — он есть и пуст; как только вариант выбран —
  // он исчезает. Это доказательство того, что ответ попал в ФОРМУ, а не только
  // нарисовался.
  const twinOf = root => root.querySelector('input[aria-hidden="true"][required]');
"""

# Пометка своя (`data-af-menu`), а не `data-af` скрапера: тот принадлежит снимку
# формы, и затирать его здесь нельзя.
_MENU_JS = _HELPERS + r"""
  const el = arguments[0];
  document.querySelectorAll('[data-af-menu]').forEach(n => n.removeAttribute('data-af-menu'));
  const m = menuOf(el);
  const opts = optionsIn(m);
  if (!opts.length) return [];
  m.setAttribute('data-af-menu', '1');
  return opts.map(o => norm(o.innerText).slice(0, 200));
"""

_STATE_JS = _HELPERS + r"""
  const el = arguments[0];
  const root = rootOf(el);
  const twin = twinOf(root);
  return {
    expanded: el.getAttribute('aria-expanded') === 'true',
    input: norm(el.value || ''),
    shown: shownIn(root),
    twin: twin ? (norm(twin.value) ? 'filled' : 'empty') : 'none',
  };
"""

_UNSTAMP_JS = (r"""() => document.querySelectorAll('[data-af-menu]')"""
               r""".forEach(n => n.removeAttribute('data-af-menu'));""")

# Варианты меню — только видимые, чтобы номер значил то же, что и в `_MENU_JS`.
_OPTION_SEL = '[data-af-menu] [role=option]:visible'


def _fn(body: str) -> str:
    """JS-выражение из тела: Playwright ждёт функцию, а `arguments` внутри
    стрелочной не работает — поэтому обычная."""
    return "function () {\n" + body + "\n}"


def _fold(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _squash(text: str) -> str:
    """Строка без пунктуации: «Bachelor's Degree» и «Bachelors Degree» — одно и
    то же, а живой список 2026-08-24 предлагает первое на ответ вторым."""
    return re.sub(r"[^0-9a-zA-Zа-яёА-ЯЁ]+", "", _fold(text))


def _starts(long: str, short: str) -> bool:
    """`long` начинается с `short` и ровно на границе слова.

    Граница здесь не для красоты: «November» начинается с «No», и без неё ответ
    «No» на вопрос с месяцами выбрал бы ноябрь.
    """
    return bool(short) and long.startswith(short) and (
        len(long) == len(short) or not long[len(short)].isalnum())


def _inside(hay: str, needle: str) -> bool:
    return bool(needle) and re.search(
        r"(?<![0-9a-zA-Zа-яёА-ЯЁ])" + re.escape(needle)
        + r"(?![0-9a-zA-Zа-яёА-ЯЁ])", hay) is not None


def _rank(option: str, value: str):
    """Насколько вариант похож на ответ; 0 — точно, None — не годится.

    Замеры 2026-08-24 показывают, зачем каждая ступень: «Kazakhstan» выбирается
    из варианта «Kazakhstan +7» (в тексте телефонный код), «Yes, I agree» — из
    «Yes», «Bachelors Degree» — из «Bachelor's Degree». Подстрокой без границ
    слова мерить нельзя: «No» лежит внутри «Not sure».
    """
    opt, val = _fold(option), _fold(value)
    if not opt or not val:
        return None
    if opt == val:
        return 0
    sq_opt, sq_val = _squash(option), _squash(value)
    if sq_opt and sq_opt == sq_val:
        return 1
    if _starts(opt, val) or (len(sq_val) >= 4 and sq_opt.startswith(sq_val)):
        return 2
    if _starts(val, opt) or (len(sq_opt) >= 4 and sq_val.startswith(sq_opt)):
        return 3
    if _inside(opt, val):
        return 4
    return None


def _best(options, value):
    """Номер самого подходящего варианта, или None.

    При равном сходстве берётся тот, что выше в списке: и Greenhouse, и LinkedIn
    ставят лучшее совпадение первым (замер: «Berlin» → «Berlin, Germany», потом
    «New Berlin, Wisconsin, United States»).
    """
    best, best_rank = None, None
    for i, text in enumerate(options):
        rank = _rank(text, value)
        if rank is not None and (best_rank is None or rank < best_rank):
            best, best_rank = i, rank
    return best


def _keys(value: str):
    """Запросы, которыми стоит поискать вариант, от точного к широкому.

    Сокращать ЗАПРОС можно, ослаблять сверку с ответом — нельзя: короткий запрос
    только расширяет список, а выбирается из него всё равно вариант, совпавший с
    полным ответом. Замеры 2026-08-24: «Berlin, Germany» находится целиком, а
    «Bachelors Degree» — только по «Bach», потому что фильтр ищет подстроку и об
    апострофе не догадывается.
    """
    keys, seen = [], set()

    def add(key):
        key = (key or "").strip()
        if key and key.lower() not in seen:
            seen.add(key.lower())
            keys.append(key)

    add(value)
    head = re.split(r"[,(/]", value)[0]      # «Berlin» из «Berlin, Germany»
    add(head)
    words = head.split()
    if words:
        add(words[0])
        add(_squash(words[0])[:4])
    return keys[:4]


def _state(locator):
    try:
        return locator.first.evaluate(_fn(_STATE_JS), timeout=_ACT_TIMEOUT_MS)
    except Exception:  # noqa: BLE001 — поля может уже не быть: форма перерисовалась
        return {}


def _pause(page, ms: int) -> None:
    try:
        page.wait_for_timeout(ms)
    except Exception:  # noqa: BLE001 — у поддельной страницы в тестах его нет
        time.sleep(ms / 1000)


def _held(state) -> str:
    """Что виджет ДЕРЖИТ сейчас: выбранный вариант, либо текст в самом поле.

    Порядок важен: после выбора react-select чистит `input.value`, поэтому поле
    пусто у заполненного виджета — а вот у типовой подсказки LinkedIn выбранное,
    наоборот, остаётся текстом в поле.
    """
    return (state.get("shown") or "").strip() or (state.get("input") or "").strip()


def combobox_value(page, locator) -> str:
    """Что в выпадающем поле выбрано. «» — ничего (или поля уже нет).

    Нужна отдельно от `fill_combobox`, потому что скрапер формы читает у поля
    `input.value`, а он у react-select пуст ВСЕГДА: и до выбора, и после.
    """
    return _held(_state(locator))


def combobox_options(page, locator, *, timeout_ms: int = _OPEN_BUDGET_MS) -> list:
    """Что поле предлагает, если его просто открыть. «[]» — прочитать не вышло.

    Нужна вызывающей стороне, чтобы было ЧЕМ отвечать. Скрапер формы видит
    react-select обычным `input[type=text]` и приносит `options: []`, поэтому
    модель отвечает на такой вопрос вслепую — и мимо: на живой форме N26 вопрос
    про GDPR предлагает единственный вариант «I Acknowledge», а на ответ «Yes»
    ни один вариант не похож (замер 2026-08-24). Поле при этом остаётся
    нетронутым: список открывается и закрывается обратно.
    """
    box = locator.first
    try:
        _open(page, box)
        # Пустой ответ не похож ни на один вариант, поэтому `_pick` здесь только
        # смотрит: нажать ему нечего.
        _, options, _ = _pick(page, box, "", time.monotonic() + timeout_ms / 1000,
                              timeout_ms, False, None)
        return options or []
    except Exception:  # noqa: BLE001 — поля может уже не быть
        return []
    finally:
        _cleanup(page, box, clear=False)


def fill_combobox(page, locator, value: str, *,
                  timeout_ms: int = TOTAL_TIMEOUT_MS) -> bool:
    """Выбрать `value` в выпадающем поле. True — только если выбор ПОДТВЕРЖДЁН.

    `locator` — контрол, уже найденный вызывающей стороной (скрапер метит их
    `data-af=<индекс>`). Наружу не выпускается ничего: любой сбой — это False,
    потому что заполнение идёт циклом по полям, и решение «звать человека или
    нет» принимает вызывающая сторона по своему правилу про обязательность.

    Не найдя подходящего варианта, поле остаётся ПУСТЫМ: случайный город в
    анкете хуже честного ручного отклика, а «оставим введённый текст» — это ровно
    тот молчаливый сбой, из-за которого форма отвечала «Please enter a valid
    answer» и никто об этом не узнавал.
    """
    if not (value or "").strip():
        return False
    box = locator.first
    ok = False
    try:
        ok = _choose(page, box, value, time.monotonic() + timeout_ms / 1000)
    except Exception:  # noqa: BLE001 — чужой виджет не должен ронять заполнение
        ok = False
    finally:
        _cleanup(page, box, clear=not ok)
    return ok


def _choose(page, box, value: str, deadline: float) -> bool:
    before = _state(box)
    # Уже выбрано то же самое — второй заход после перерисовки формы не должен
    # открывать меню и выбирать заново.
    if _rank(_held(before), value) in (0, 1):
        return True
    _open(page, box)
    seen, whole = None, None
    for key in [None] + _keys(value):
        typed = key is not None
        if typed and not _typed(box, key):
            continue
        picked, seen, settled = _pick(
            page, box, value, deadline,
            _TYPED_BUDGET_MS if typed else _OPEN_BUDGET_MS, typed, seen)
        if picked:
            # Вариант нажат: либо форма его приняла, либо это уже не наш случай —
            # жать наугад следующий значит записать в анкету не тот ответ.
            return _confirm(box, before, picked)
        if not typed:
            whole = seen if settled else None
        elif settled and whole and set(seen) <= set(whole):
            # Список только сужается — значит фильтр местный, и весь набор мы уже
            # видели при открытии. Совпадения в нём не было, а более короткий
            # запрос ничего нового не покажет.
            break
        if time.monotonic() >= deadline:
            break
    return False


def _open(page, box) -> None:
    """Раскрыть список — а не переключить его.

    Клик по УЖЕ открытому react-select закрывает меню. Замер 2026-08-24: прочитав
    варианты «Degree» и сразу нажав поле, чтобы ответить, мы получали закрытый
    список, ноль вариантов и «не смог заполнить» на ровном месте. Поэтому сначала
    смотрим, открыт ли он, а второй клик делаем, только если первого не хватило.
    """
    if _is_open(page, box):
        return
    box.click(timeout=_ACT_TIMEOUT_MS)
    if not _is_open(page, box):
        box.click(timeout=_ACT_TIMEOUT_MS)


def _is_open(page, box) -> bool:
    if _state(box).get("expanded"):
        return True
    try:
        return bool(box.evaluate(_fn(_MENU_JS), timeout=_ACT_TIMEOUT_MS))
    except Exception:  # noqa: BLE001
        return False


def _typed(box, key: str) -> bool:
    """Вписать запрос в поле. False — вписать не удалось.

    `fill` вместо посимвольного ввода: замер 2026-08-24 на живых формах
    Greenhouse — меню открывается и фильтруется от него так же, как от
    клавиатуры, а секунда на поле экономится. Поле, в которое писать нельзя
    (react-select без поиска), — не ошибка: список у него и так весь на виду.
    """
    try:
        box.fill(key, timeout=_ACT_TIMEOUT_MS)
        return True
    except Exception:  # noqa: BLE001
        return False


def _pick(page, box, value: str, deadline: float, budget_ms: int,
          typed: bool, was):
    """Дождаться подходящего варианта и нажать его.

    Возвращает (текст нажатого варианта, последний виденный список, окончателен
    ли он). Ждём не время, а появление ВАРИАНТА: пока ответ сервера в пути, в
    меню висят варианты прошлого запроса, и «первый попавшийся» — это «3iL
    Limoges» вместо нужного вуза.

    Окончательным список считается, когда он не пуст, отличается от того, что
    висел до нашего запроса (то есть виджет на запрос уже ответил), и с тех пор
    не менялся. Дожидаться в такой ситуации нечего — совпадения в нём нет.
    """
    end = min(time.monotonic() + budget_ms / 1000, deadline)
    last, since = None, time.monotonic()
    while True:
        options = box.evaluate(_fn(_MENU_JS), timeout=_ACT_TIMEOUT_MS)
        now = time.monotonic()
        if options != last:
            last, since = options, now
        idx = _best(options, value)
        if idx is not None:
            option = page.locator(_OPTION_SEL).nth(idx)
            # Список мог перерисоваться между чтением и нажатием — тогда номер
            # указывает уже на другой вариант, и жать его нельзя.
            if _fold(option.inner_text(timeout=_ACT_TIMEOUT_MS)) == _fold(options[idx]):
                option.click(timeout=_CLICK_TIMEOUT_MS)
                return options[idx], options, False
        answered = options != was if typed else True
        if options and answered and now - since >= _SETTLE_MS / 1000:
            return "", options, True
        if now >= end:
            return "", options, False
        _pause(page, _POLL_MS)


def _confirm(box, before, option: str) -> bool:
    """Убедиться, что выбор попал в форму, а не только нарисовался.

    Читать `input.value` тут бесполезно — он пуст и до, и после. Годятся: узел с
    выбранным значением, исчезнувший служебный `<input required aria-hidden>` и
    текст в самом поле (так хранит выбор подсказка LinkedIn).

    Сверка с нажатым вариантом — не «текст совпал»: у поля «Country» вариант
    называется «Kazakhstan +7», а на экране остаётся только «+7», потому что
    страна нарисована флагом (замер 2026-08-24 на N26).
    """
    after = _state(box)
    if not after:
        return False
    shown = _held(after)
    filled = bool(shown) or (before.get("twin") == "empty" and after.get("twin") != "empty")
    if not filled:
        return False
    if not shown:
        return True
    opt, val = _fold(option), _fold(shown)
    return val == opt or val in opt or opt in val or _rank(shown, option) is not None


def _cleanup(page, box, clear: bool) -> None:
    """Убрать за собой: закрыть список, снять пометку меню и, после неудачи,
    очистить поле — чтобы форма осталась такой, какой мы её нашли.

    Закрываем расфокусировкой, а не Escape: react-select с `escapeClearsValue`
    понимает Escape при закрытом меню как «стереть выбор» (кнопка «Clear
    selections» у полей Greenhouse есть), и на уже заполненном поле это стёрло бы
    ответ. А закрывать надо обязательно: открытое меню накрывает соседние
    вопросы, и клик по следующему до него не доходит — замер 2026-08-24, после
    чтения вариантов «Degree*» поле «End date month*» не открывалось вовсе.
    """
    try:
        if clear:
            box.fill("", timeout=_ACT_TIMEOUT_MS)
    except Exception:  # noqa: BLE001
        pass
    try:
        box.blur(timeout=_ACT_TIMEOUT_MS)
    except Exception:  # noqa: BLE001
        pass
    try:
        page.evaluate(_UNSTAMP_JS)
    except Exception:  # noqa: BLE001
        pass
