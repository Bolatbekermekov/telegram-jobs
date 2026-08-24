"""Прикрепление файла к чужой форме — с доказательством, что он прикрепился.

Зачем отдельный модуль. Заявка без резюме однажды уже ушла (Ashby, лид 123,
2026-07-29), поэтому «команда set_input_files не бросила исключение» никогда не
считалось за прикрепление: проверялось `input.files.length`. На Teamtailor эта
проверка развернулась другой стороной — замер живой формы 2026-08-24
(careers.bluethrone.io, вакансия 8175038, лид 419):

    t+0     set_input_files на #candidate_resume_remote_url (класс dz-hidden-input)
    t+~10   Dropzone забирает FileList и УДАЛЯЕТ input из DOM
    t+124   в previewsContainer появляется <a data-dz-name>probe_cv.pdf</a>,
            загрузка ещё идёт
    t+227   POST /uploads/presigned_data → 200, следом POST в S3 → 201
    t+818   на превью встают классы dz-success dz-complete, у него
            data-…-upload-preview-url-value = https://…s3…/tmpuploads/<uuid>/probe_cv.pdf,
            и ровно эта ссылка лежит в ОТПРАВЛЯЕМОМ поле
            <input type=text name="candidate[resume_remote_url]">;
            input[type=file] возвращается в DOM новым, пустым и уже без required

То есть на Teamtailor `files.length` равен нулю всегда — по устройству виджета, а
не по ошибке. Старая проверка читала этот ноль, догружала файл второй раз (ещё
одна копия в S3), снова читала ноль и звала человека к форме, которая была готова
к отправке.

Поэтому доказательством считается ЛЮБОЕ из двух, но только оно:
  * файл лежит в самом входе (`files.length > 0`) — так устроены Greenhouse,
    Ashby, Lever, LinkedIn: FileList и есть то, что уйдёт на сервер;
  * внутри блока виджета появилось НОВОЕ отправляемое поле со ссылкой на
    загруженный файл — так устроен Teamtailor: на сервер уйдёт ссылка.

Имя файла на экране доказательством НЕ считается: на живом Teamtailor оно
появляется за 700 мс до того, как файл долетает до S3, а на отвергнутом файле
(чужой тип) виджет отвечает «You can't upload files of this type» — снаружи это
неотличимо от «ещё грузится», если верить надписи.

Автоматизация чужих ATS нарушает их ToS и грозит банами (принято пользователем).
"""
import os
import uuid

# Сколько ждать доказательства. Живой Teamtailor уложился в 820 мс на файле в
# 600 байт; настоящее резюме на сотни килобайт и на плохом канале — дольше, а
# лишнее ожидание стоит секунд, тогда как его нехватка стоит ручного отклика.
PROOF_TIMEOUT_MS = 8000
_POLL_MS = 250
_SET_TIMEOUT_MS = 8000

# Метки блока виджета и самого входа. Как и `data-af` у скрапера, это наши
# атрибуты, и живут они ровно на время одной попытки: перерисовка их снимает,
# поэтому обе ставятся заново на каждом опросе, а в конце убираются.
_BLOCK_ATTR = "data-afu"
_ELEM_ATTR = "data-afu-el"

# Чем виджет говорит, что файл не принят. Тексты сняты живьём: Teamtailor на
# чужом типе отвечает «You can't upload files of this type. Allowed types: …».
# Нужно это не для правильности (без доказательства ответ и так False), а чтобы
# не грузить отвергнутый файл второй раз и не ждать полный таймаут дважды.
#
# Засчитывается только текст, которого до загрузки НЕ БЫЛО. Половина ATS пишет
# рядом с зоной «Accepted file types: PDF, DOC» — теми же словами, какими другая
# половина сообщает об отказе, и по неподвижной подсказке виджет объявлял бы отказ
# ещё до того, как файл долетит.
_ERROR_RE = (r"can.{0,2}t upload|cannot upload|not allowed|invalid file"
             r"|unsupported|file type|too (large|big)|exceeds|upload failed"
             r"|ошибк|не удалось|недопустим|слишком больш")

# Приметы входа снимаются с ЖИВОГО элемента до установки файла: id, aria-label,
# name и место среди файловых входов страницы. По ним он потом и ищется —
# `data-af` тут только первым и самым дешёвым вариантом, потому что Dropzone
# пересоздаёт узел и наша метка пропадает вместе со старым.
_FINGERPRINT_JS = r"""(el) => ({
  idx: [...document.querySelectorAll('input[type=file]')].indexOf(el),
  id: el.id || '',
  label: el.getAttribute('aria-label') || '',
  name: el.name || '',
  af: el.getAttribute('data-af') || '',
})"""

# Что видно про загрузку прямо сейчас.
#
# Вход ищется по приметам, а не по локатору, потому что узла может уже не быть:
# Dropzone удаляет input сразу и возвращает новый только после ответа S3 — между
# t+10 и t+818 на живой форме входа с таким id в DOM НЕТ вообще.
#
# Блок виджета — самый большой предок, внутри которого всё ещё ровно один
# input[type=file]. Граница не выдумана, а измерена: на живой форме превью со
# ссылкой лежит на два уровня выше входа (сосед зоны перетаскивания, а не её
# потомок), а уже на следующем уровне в один предок попадают все три загрузки
# страницы — «Upload CV», «Additional files» и видео-ответ. Искать выше значит
# засчитать чужую загрузку за свою.
#
# Значения полей читаются свойством `value`, а не атрибутом: Teamtailor создаёт
# поле со ссылкой пустым и наполняет его из JS, так что в разметке страницы там
# навсегда value="".
_STATE_JS = r"""(fp) => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const all = [...document.querySelectorAll('input[type=file]')];
  const match = e =>
       (fp.af && e.getAttribute('data-af') === fp.af)
    || (fp.id && e.id === fp.id)
    || (fp.label && e.getAttribute('aria-label') === fp.label)
    || (fp.name && e.name && e.name === fp.name);
  let block = document.querySelector('[' + fp.blockAttr + '="' + fp.token + '"]');
  const inBlock = block ? [...block.querySelectorAll('input[type=file]')] : [];
  const el = inBlock.find(match) || all.find(match) || inBlock[0]
          || (fp.idx >= 0 && fp.idx < all.length ? all[fp.idx] : null);
  if (!block && el) {
    for (let n = el.parentElement, i = 0; n && i < 6; n = n.parentElement, i++) {
      if (n.tagName === 'BODY' || n.tagName === 'HTML') break;
      if (n.querySelectorAll('input[type=file]').length > 1) break;
      block = n;
    }
  }
  if (block) block.setAttribute(fp.blockAttr, fp.token);
  if (el) el.setAttribute(fp.elemAttr, fp.token);
  const scope = block || el;
  // Ссылка на загруженный файл: URL, путь или длинный непрозрачный ключ. Голое
  // имя файла в поле — то же самое, что имя на экране, и не доказывает ничего.
  const isRef = v => /^(https?:|blob:|data:)/i.test(v) || v.includes('/')
                  || (v.length >= 16 && !/\s/.test(v) && v !== fp.base);
  const skip = ['file', 'submit', 'button', 'reset', 'image', 'checkbox', 'radio'];
  const refs = scope
    ? [...scope.querySelectorAll('input,textarea')]
        .filter(e => !skip.includes((e.type || '').toLowerCase()) && !e.disabled)
        .map(e => norm(e.value)).filter(v => v && isRef(v))
    : [];
  const text = scope ? norm(scope.innerText || scope.textContent || '') : '';
  return {
    files: el && el.files ? el.files.length : 0,
    refs: refs,
    error: new RegExp(fp.errorRe, 'i').test(text),
  };
}"""

_CLEANUP_JS = r"""(fp) => {
  const sel = '[' + fp.blockAttr + '="' + fp.token + '"],'
            + '[' + fp.elemAttr + '="' + fp.token + '"]';
  document.querySelectorAll(sel).forEach(e => {
    e.removeAttribute(fp.blockAttr);
    e.removeAttribute(fp.elemAttr);
  });
}"""


def _pause(page, ms: int) -> None:
    try:
        page.wait_for_timeout(ms)
    except Exception:  # noqa: BLE001 — у фейковой страницы нет часов
        pass


def _state(page, fp: dict) -> dict:
    """Замер состояния загрузки; недоступная страница — это «доказательств нет»."""
    try:
        return page.evaluate(_STATE_JS, fp)
    except Exception:  # noqa: BLE001 — страница могла перерисовываться прямо сейчас
        return {"files": 0, "refs": [], "error": False}


def _proved(state: dict, before: set) -> bool:
    if int(state.get("files") or 0) > 0:
        return True
    return bool(set(state.get("refs") or []) - before)


def attach_file(page, locator, path: str, *,
                proof_timeout_ms: int = PROOF_TIMEOUT_MS) -> bool:
    """Приложить файл к контролу и вернуть, доказано ли, что он прикрепился.

    `locator` — уже найденный вызывающей стороной `input[type=file]` (у внешнего
    отклика это `[data-af=<индекс>]`). Наружу не выпускается ничего: любой сбой —
    это False, потому что решение вызывающей стороны бинарное — отправлять заявку
    или звать человека, — и упавший прогон тут не помогает никому.

    True возвращается ТОЛЬКО по доказательству: файл лежит во входе, либо в блоке
    виджета появилась новая ссылка на загрузку. Не дождавшись ни того ни другого,
    файл прикладывается второй раз — на Ashby (2026-07-29) первая установка
    ложится на узел, который перерисовка тут же выбрасывает, и спасает ровно
    повтор по заново найденному входу.
    """
    fp = None
    try:
        if not path or not os.path.isfile(path):
            return False
        # Локатор мог протухнуть: форму перерисовали между «нашли» и «прикладываем».
        # Без этой проверки `evaluate` ждёт элемент СВОИ 30 секунд по умолчанию —
        # столько прогон стоять не должен, а ответ всё равно был бы False.
        if locator.count() == 0:
            return False
        fp = locator.first.evaluate(_FINGERPRINT_JS, timeout=_SET_TIMEOUT_MS)
        fp.update(base=os.path.basename(path), token="u" + uuid.uuid4().hex[:12],
                  blockAttr=_BLOCK_ATTR, elemAttr=_ELEM_ATTR, errorRe=_ERROR_RE)
        # Что в блоке лежало ДО нас. Засчитывается только НОВАЯ ссылка: у соседней
        # загрузки («Additional files» стоит на той же форме) своя, и общий предок
        # у них есть — на Ashby заявка без резюме ушла именно потому, что чужой
        # признак сошёл за свой.
        was = _state(page, fp)
        before = set(was.get("refs") or [])
        complained = bool(was.get("error"))
        for attempt in (1, 2):
            # Вторая попытка идёт по метке, поставленной последним замером: свой
            # локатор вызывающей стороны к этому моменту может указывать в узел,
            # которого больше нет.
            target = locator.first if attempt == 1 else page.locator(
                f'[{_ELEM_ATTR}="{fp["token"]}"]').first
            try:
                target.set_input_files(path, timeout=_SET_TIMEOUT_MS)
            except Exception:  # noqa: BLE001 — узла может уже не быть
                if attempt == 2:
                    return False
                _state(page, fp)          # обновить метку перед повтором
                continue
            waited, rejected = 0, False
            while True:
                st = _state(page, fp)
                if _proved(st, before):
                    return True
                rejected = bool(st.get("error")) and not complained
                if rejected or waited >= proof_timeout_ms:
                    break
                _pause(page, _POLL_MS)
                waited += _POLL_MS
            if rejected:
                return False
        return False
    except Exception:  # noqa: BLE001 — см. докстроку: наружу только True/False
        return False
    finally:
        if fp is not None:
            try:
                page.evaluate(_CLEANUP_JS, fp)
            except Exception:  # noqa: BLE001 — уборка меток не повод падать
                pass
