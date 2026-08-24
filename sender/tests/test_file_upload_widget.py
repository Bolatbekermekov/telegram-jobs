"""Прикрепление файла к виджету загрузки — на разметке, снятой с живого
Teamtailor 2026-08-24 (careers.bluethrone.io, вакансия 8175038).

Живой прогон (лид 419) дошёл до формы и встал на «резюме не прикрепилось к
обязательному полю „Drop your file or upload, Upload CV“». Замер показал, что
резюме там как раз прикреплялось: `set_input_files` → Dropzone забирает FileList,
POST /uploads/presigned_data, POST в S3 (201), и через ~820 мс ссылка на файл
лежит в отправляемом поле `candidate[resume_remote_url]`. Но сам `input[type=file]`
Dropzone по устройству УДАЛЯЕТ и пересоздаёт пустым, поэтому `input.files.length`
там навсегда 0 — проверка, на которой стоял внешний отклик, читала ноль и звала
человека к форме, которая была готова к отправке.

Отсюда два конца, которые держат эти тесты: обычный `input`, где доказательство —
это и есть `files`, и виджет, где доказательство — ссылка на загрузку в поле
формы. И граница между ними: имя файла на экране НЕ доказательство (на живом
Teamtailor оно появляется на t+124 мс, когда файл ещё летит в S3 и может быть
отвергнут), чужая загрузка по соседству — тоже не наша.

Браузер настоящий, но сеть не нужна: разметка подаётся через `set_content`,
поэтому тесты детерминированные и в метку `live` не попадают. Живой тест на
настоящую форму помечен `live` и НИЧЕГО НЕ ОТПРАВЛЯЕТ — только прикрепляет файл.
"""
import pytest

from app.infrastructure.widgets.file_upload import attach_file


@pytest.fixture(scope="module")
def page():
    pw = pytest.importorskip("patchright.sync_api")
    try:
        p = pw.sync_playwright().start()
        browser = p.chromium.launch(headless=True, channel="chrome")
    except Exception as exc:  # noqa: BLE001 — без Chrome тест не запускается
        pytest.skip(f"нет браузера: {type(exc).__name__}")
    page = browser.new_context().new_page()
    yield page
    browser.close()
    p.stop()


@pytest.fixture(scope="module")
def cv(tmp_path_factory):
    """Файл для прикрепления. НЕ из sender/cv — там настоящие резюме."""
    path = tmp_path_factory.mktemp("upload") / "probe_cv.pdf"
    path.write_bytes(b"%PDF-1.4\n% probe, not a real resume\n%%EOF\n")
    return str(path)


# --- разметка ----------------------------------------------------------------

# Скрипт-двойник Dropzone, которым Teamtailor принимает резюме. Повторяет ровно
# то, что снято с живой формы 2026-08-24:
#   1) на `change` виджет забирает файл и НЕМЕДЛЕННО заменяет input новым, пустым
#      (у живого при этом пропадает и `required`, и наш `data-af`);
#   2) через ~120 мс показывает имя файла — загрузка ещё идёт;
#   3) через ~820 мс кладёт ссылку на залитый файл в отправляемое поле
#      `candidate[resume_remote_url]` — вот это и есть «файл принят».
# Задержки здесь короче живых: проверяется порядок событий, а не скорость S3.
DROPZONE_JS = """
// Пустой двойник входа. Именно createElement, а не cloneNode: Chrome при
// клонировании файлового входа ПЕРЕНОСИТ и выбранные файлы (замер 2026-08-24:
// clone.files.length === 1), так что клон изобразил бы обратное тому, что делает
// живой виджет. Настоящий Dropzone тоже строит вход заново (setupHiddenFileInput),
// и на живом Teamtailor у нового входа уже нет ни required, ни нашего data-af.
function blank(inp) {
  const fresh = document.createElement('input');
  fresh.type = 'file';
  for (const a of ['class', 'id', 'aria-label', 'accept'])
    if (inp.hasAttribute(a)) fresh.setAttribute(a, inp.getAttribute(a));
  inp.parentNode.replaceChild(fresh, inp);
  return fresh;
}

function dropzone(id, opts) {
  const wire = (inp) => inp.addEventListener('change', () => {
    const f = inp.files[0];
    if (!f) return;
    const box = document.getElementById(opts.previews);
    // Dropzone пересоздаёт скрытый вход — файл в нём не остаётся.
    wire(blank(inp));
    if (opts.reject) { box.innerHTML = '<p>' + opts.reject + '</p>'; return; }
    setTimeout(() => {
      box.innerHTML = '<a data-dz-name>' + f.name + '</a>';
    }, opts.chipDelay);
    if (opts.link) setTimeout(() => {
      const url = document.createElement('input');
      url.type = 'text';
      url.name = 'candidate[resume_remote_url]';
      url.value = 'https://teamtailor-production.s3.eu-west-1.amazonaws.com'
                + '/tmpuploads/6929e3f8-c304-4f8e-b5c0-fa48ff99ebfd/' + f.name;
      box.appendChild(url);
    }, opts.linkDelay);
  });
  wire(document.getElementById(id));
}
"""


def upload_block(idx: int, label: str = "Upload CV") -> str:
    """Поле загрузки Teamtailor: подпись, зона перетаскивания и превью рядом.

    Вход лежит НЕ рядом с превью, а на уровень глубже, внутри зоны перетаскивания
    (замер живой формы: превью — сосед зоны, а не её потомок). Поэтому виджет и
    приходится искать подъёмом по предкам, а не через `parentElement`.
    """
    return f"""
<div class="field">
  <label for="cv{idx}">{label}</label>
  <div class="trigger">
    <input type="file" class="dz-hidden-input" id="cv{idx}"
           aria-label="Drop your file or upload, {label}" accept=".pdf" required>
  </div>
  <div class="previews" id="prev{idx}"></div>
</div>"""


def render(page, body: str, script: str = "") -> None:
    page.set_content(f"<body><form>{body}</form>"
                     f"<script>{DROPZONE_JS}{script}</script></body>")


def file_input(page, idx: int):
    return page.locator(f"#cv{idx}")


# --- обычный input -----------------------------------------------------------

def test_plain_input_is_proved_by_its_own_filelist(page, cv):
    """Ловит потерю простого случая: у Greenhouse/Ashby доказательство — сам FileList.

    Если бы виджет требовал непременно ссылку на загрузку, обычная форма без
    всякого JS перестала бы считаться заполненной.
    """
    render(page, upload_block(1))
    assert attach_file(page, file_input(page, 1), cv) is True
    assert page.locator("#cv1").evaluate("el => el.files.length") == 1


# --- Teamtailor / Dropzone ---------------------------------------------------

def test_dropzone_that_empties_the_input_is_proved_by_the_upload_link(page, cv):
    """Тот самый сбой лида 419: файл загружен, а `files.length` равен нулю.

    Пока доказательством считался только FileList, готовая к отправке форма
    Teamtailor уходила человеку с «резюме не прикрепилось».
    """
    render(page, upload_block(2),
           "dropzone('cv2', {previews:'prev2', chipDelay:60, "
           "link:true, linkDelay:400});")
    assert attach_file(page, file_input(page, 2), cv) is True
    assert page.locator("#cv2").evaluate("el => el.files.length") == 0


def test_filename_on_screen_is_not_proof_by_itself(page, cv):
    """Ловит соблазн поверить надписи: имя файла Teamtailor рисует на t+124 мс,
    когда файл ещё летит в S3 и вполне может быть отвергнут. Доказательство —
    только ссылка на загрузку в отправляемом поле; виджет, который имя показал,
    а ссылку так и не выдал, файл не принял.
    """
    render(page, upload_block(3),
           "dropzone('cv3', {previews:'prev3', chipDelay:60, link:false});")
    assert attach_file(page, file_input(page, 3), cv, proof_timeout_ms=1200) is False


def test_rejected_file_is_not_attached(page, cv):
    """Ловит ложное «прикрепилось» на отказе. Живой Teamtailor на чужом типе
    отвечает «You can't upload files of this type…», превью не создаёт и вход
    очищает — снаружи это неотличимо от «ещё грузится», если не читать текст.
    """
    render(page, upload_block(4),
           "dropzone('cv4', {previews:'prev4', "
           "reject:\"You can't upload files of this type. Allowed types: .pdf\"});")
    assert attach_file(page, file_input(page, 4), cv, proof_timeout_ms=1200) is False


def test_a_hint_about_allowed_types_is_not_a_refusal(page, cv):
    """Ловит ложный отказ по подсказке: половина ATS пишет рядом с зоной загрузки
    «Accepted file types: PDF, DOC» — теми же словами, какими Teamtailor сообщает
    об отказе. Если читать текст блока как есть, форма с подсказкой отказывалась
    бы принимать резюме ещё до того, как файл долетит.
    """
    render(page, upload_block(10).replace(
               '<div class="previews"',
               '<p>Accepted file types: .pdf — files too large will be rejected</p>'
               '<div class="previews"'),
           "dropzone('cv10', {previews:'prev10', chipDelay:60, "
           "link:true, linkDelay:400});")
    assert attach_file(page, file_input(page, 10), cv) is True


def test_a_neighbours_upload_is_not_our_proof(page, cv):
    """Ловит утечку через соседа: на живой форме рядом с «Upload CV» стоит
    «Additional files», и оба виджета сходятся в общем предке. Если искать
    доказательство слишком высоко, чужая загрузка засчитается за нашу — и заявка
    уйдёт без резюме, ровно как когда-то на Ashby.
    """
    render(page, upload_block(5) + upload_block(6, "Additional files"),
           "dropzone('cv5', {previews:'prev5', chipDelay:60, link:false});"
           # сосед догружает СВОЙ файл прямо во время нашей попытки
           "setTimeout(() => {"
           " const u = document.createElement('input');"
           " u.type='text'; u.name='candidate[file_remote_url]';"
           " u.value='https://teamtailor-production.s3.eu-west-1.amazonaws.com"
           "/tmpuploads/aaaa/other.pdf';"
           " document.getElementById('prev6').appendChild(u); }, 300);")
    assert attach_file(page, file_input(page, 5), cv, proof_timeout_ms=1200) is False


def test_file_lost_to_a_rerender_is_attached_again(page, cv):
    """Ловит возврат старого ашбиевского сбоя: файл ложится на узел, который
    перерисовка тут же выбрасывает, и новый вход приходит пустым. Одной попытки
    мало — виджет обязан найти вход заново и приложить файл ещё раз.
    """
    render(page, upload_block(7),
           # Узел подменяется ТОЛЬКО на первой установке — как React при первом
           # рендере формы; вторая попытка должна удержаться.
           "(function(){ let first = true;"
           " const wire = (inp) => inp.addEventListener('change', () => {"
           "   if (!first) return; first = false; wire(blank(inp)); });"
           " wire(document.getElementById('cv7')); })();")
    assert attach_file(page, file_input(page, 7), cv, proof_timeout_ms=1200) is True
    assert page.locator("#cv7").evaluate("el => el.files.length") == 1


# --- поведение при поломке ---------------------------------------------------

def test_nothing_escapes_when_the_control_is_gone(page, cv):
    """Ловит исключение наружу: вызывающая сторона решает по True/False, а не
    ловит падение. Локатор, который ни во что не попадает, — это «не удалось».
    """
    render(page, upload_block(8))
    assert attach_file(page, page.locator("#no-such-control"), cv,
                       proof_timeout_ms=600) is False


def test_nothing_escapes_when_the_page_is_broken(page, cv):
    """То же самое, но ломается сама страница: подсунут объект, который на любой
    вызов бросает. Виджет не должен уронить прогон.
    """
    class Boom:
        def __getattr__(self, name):
            raise RuntimeError("страница отвалилась")

    assert attach_file(Boom(), Boom(), cv) is False


def test_a_missing_file_is_not_attached(page, cv):
    """Ловит попытку выдать успех, когда прикладывать нечего: путь к файлу может
    прийти пустым или указывать в никуда, и `set_input_files` тогда бросает.
    """
    render(page, upload_block(9))
    assert attach_file(page, file_input(page, 9), "") is False
    assert attach_file(page, file_input(page, 9), "/nope/missing_cv.pdf") is False


# --- живая форма -------------------------------------------------------------

@pytest.mark.live
def test_live_teamtailor_attaches_the_cv(cv):
    """Живой Teamtailor: прикрепить резюме и доказать это. НИЧЕГО НЕ ОТПРАВЛЯЕТ —
    ни одной кнопки на форме не нажимается.
    """
    pw = pytest.importorskip("patchright.sync_api")
    url = ("https://careers.bluethrone.io/jobs/"
           "8175038-senior-backend-engineer-golang/applications/new")
    p = pw.sync_playwright().start()
    browser = p.chromium.launch(headless=True, channel="chrome")
    try:
        page = browser.new_context().new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(4000)
        cvinput = page.locator("#candidate_resume_remote_url[type=file]")
        assert attach_file(page, cvinput, cv) is True
        # То, что уйдёт на сервер вместе с анкетой.
        sent = page.locator('input[name="candidate[resume_remote_url]"]')
        assert sent.first.input_value().startswith("https://")
    finally:
        browser.close()
        p.stop()
