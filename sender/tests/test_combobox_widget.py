"""Выпадающее поле react-select: выбрать вариант, а не написать текст рядом.

Прогон 2026-08-24 упёрся в это дважды: «внешняя форма: не смог заполнить
обязательное поле «Location (City)*»» на вакансии N26 и то же самое на «School*»
у Datadog. Разметка ниже снята живьём в тот же день с
`job-boards.greenhouse.io/embed/job_app?for=n26&token=7925103` и
`…?for=datadog&token=8052095`; поведение виджета (когда появляется список, что
происходит с полем после выбора) воспроизведено по замерам.

Браузер настоящий, сеть не нужна: разметка подаётся через `set_content`, как в
`test_scrape_form.py`. Живые проверки помечены `live` и в обычный прогон не
попадают.
"""
import pytest

from app.infrastructure.widgets.combobox import (
    combobox_options, combobox_value, fill_combobox,
)

# Мини-react-select, повторяющий замеры 2026-08-24 на формах Greenhouse:
#  * до открытия вариантов в DOM НЕТ вообще — `aria-controls` у поля нет тоже;
#  * по клику появляется `div.select__menu > [role=listbox]#react-select-<id>-listbox`
#    внутри `.select-shell`, а поле получает `aria-controls` с его id;
#  * список фильтруется по подстроке; у асинхронного поля (School, Location)
#    ответ приходит с задержкой, и всё это время в меню видны СТАРЫЕ варианты;
#  * после выбора: меню исчезает, `aria-controls` снимается, ввод очищается
#    (`input.value === ''`!), плейсхолдер заменяется на `div.select__single-value`,
#    а служебный `<input required aria-hidden>` — тот, которым браузер ругается на
#    пустой выбор, — удаляется из DOM;
#  * клик по УЖЕ открытому полю его закрывает, уход фокуса — тоже, а нажатие на
#    вариант фокус не отбирает (react-select гасит `mousedown` в меню).
WIDGET_JS = r"""
document.querySelectorAll('input.select__input').forEach(inp => {
  const shell = inp.closest('.select-shell');
  const vc = inp.closest('.select__value-container');
  const all = () => JSON.parse(inp.dataset.options || '[]');
  const wait = Number(inp.dataset.async || 0);
  const listId = 'react-select-' + inp.id + '-listbox';
  let menu = null, timer = null;
  const match = q => all().filter(t => t.toLowerCase().includes((q||'').toLowerCase()));
  function render(list) {
    if (!menu) {
      menu = document.createElement('div');
      menu.className = 'select__menu remix-css-1oc7h4y-menu';
      menu.innerHTML = '<div class="select__menu-list remix-css-qr46ko" role="listbox"'
                     + ' aria-multiselectable="false" id="' + listId + '"></div>';
      // Нажатие на вариант не должно уводить фокус: иначе поле теряет его
      // раньше, чем клик доходит до варианта. react-select гасит это так же.
      menu.addEventListener('mousedown', e => e.preventDefault());
      shell.appendChild(menu);
    }
    const ml = menu.firstChild;
    ml.innerHTML = '';
    list.forEach((t, i) => {
      const d = document.createElement('div');
      d.className = 'select__option' + (i === 0 ? ' select__option--is-focused' : '');
      d.setAttribute('role', 'option');
      d.setAttribute('aria-disabled', 'false');
      d.id = 'react-select-' + inp.id + '-option-' + i;
      d.textContent = t;
      d.addEventListener('click', () => choose(t));
      ml.appendChild(d);
    });
  }
  function open() {
    inp.setAttribute('aria-expanded', 'true');
    inp.setAttribute('aria-controls', listId);
    render(match(inp.value));
  }
  function close() {
    inp.setAttribute('aria-expanded', 'false');
    inp.removeAttribute('aria-controls');
    if (menu) { menu.remove(); menu = null; }
  }
  function choose(t) {
    close();
    inp.value = '';
    const ph = vc.querySelector('.select__placeholder');
    if (ph) ph.remove();
    let sv = vc.querySelector('.select__single-value');
    if (!sv) {
      sv = document.createElement('div');
      sv.className = 'select__single-value remix-css-1dimb5e-singleValue';
      vc.insertBefore(sv, vc.firstChild);
    }
    sv.textContent = inp.dataset.shows || t;
    vc.classList.add('select__value-container--has-value');
    const twin = shell.querySelector('input[aria-hidden="true"][required]');
    if (twin) twin.remove();
  }
  inp.addEventListener('click', () => {
    if (inp.getAttribute('aria-expanded') === 'true') { close(); return; }
    open();
  });
  inp.addEventListener('blur', close);
  inp.addEventListener('input', () => {
    // Закрытый список от ввода не открывается: замер 2026-08-24 — по закрытому
    // полю ответ не проходил вообще, сколько в него ни пиши.
    if (inp.getAttribute('aria-expanded') !== 'true') return;
    if (timer) clearTimeout(timer);
    if (!wait) { render(match(inp.value)); return; }
    const q = inp.value;
    timer = setTimeout(() => {
      if (inp.getAttribute('aria-expanded') === 'true') render(match(q));
    }, wait);
  });
  inp.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
});
"""

# Телефонный виджет intl-tel-input, который живёт на КАЖДОЙ форме Greenhouse
# рядом с полем «Phone». Его список из 244 стран лежит в DOM с загрузки страницы
# и скрыт классом `iti__hide`. Именно он ломал прежний способ заполнения.
ITI_DECOY = """
<div id="iti-0__dropdown-content" class="iti__dropdown-content iti__hide"
     style="display:none" role="dialog">
  <ul class="iti__country-list" id="iti-0__country-listbox" role="listbox">
    <li id="iti-0__item-af" class="iti__country iti__highlight" role="option"
        aria-selected="false">Afghanistan+93</li>
    <li id="iti-0__item-ax" class="iti__country" role="option"
        aria-selected="false">Åland Islands+358</li>
    <li id="iti-0__item-al" class="iti__country" role="option"
        aria-selected="false">Albania+355</li>
  </ul>
</div>
"""


def gh_select(field_id, label, options, *, required=True, async_ms=0, shows=""):
    """Один выпадающий вопрос новой формы Greenhouse — как в живой разметке."""
    import html
    import json

    # Через `html.escape`: в вариантах есть апострофы («Bachelor's Degree»), и
    # без экранирования они рвут сам атрибут.
    packed = html.escape(json.dumps(options), quote=True)
    twin = ('<input required tabindex="-1" aria-hidden="true" '
            'class="remix-css-1a0ro4n-requiredInput" value="">') if required else ""
    return f"""
<div class="select__container select__container--outside-label">
  <label id="{field_id}-label" for="{field_id}" class="label select__label"
    >{label}<span aria-hidden="true">*</span></label>
  <div class="select-shell remix-css-b62m3t-container">
    <span id="react-select-{field_id}-live-region" class="remix-css-7pg0cj-a11yText"></span>
    <span aria-live="polite" role="log" class="remix-css-7pg0cj-a11yText"></span>
    <div><div class="select__control remix-css-13cymwt-control">
      <div class="select__value-container remix-css-hlgwow">
        <div class="select__placeholder" id="react-select-{field_id}-placeholder">Select...</div>
        <div class="select__input-container" data-value="">
          <input class="select__input" id="{field_id}" type="text" role="combobox"
                 aria-autocomplete="list" aria-expanded="false" aria-haspopup="true"
                 aria-labelledby="{field_id}-label" aria-required="{str(required).lower()}"
                 autocomplete="off" spellcheck="false" tabindex="0" value=""
                 data-af="{field_id}" data-shows="{shows}"
                 data-async="{async_ms}" data-options="{packed}">
        </div>
      </div>
      <div class="select__indicators remix-css-1wy0on6"></div>
    </div></div>
    {twin}
  </div>
</div>
"""


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


def build(page, *fields):
    page.set_content(f"<body>{ITI_DECOY}{''.join(fields)}"
                     f"<script>{WIDGET_JS}</script></body>")


def box(page, field_id):
    return page.locator(f'[data-af="{field_id}"]')


DEGREES = ["Associate's Degree", "Bachelor's Degree", "Doctor of Medicine (M.D.)",
           "Doctor of Philosophy (Ph.D.)", "Engineer's Degree", "High School",
           "Master's Degree", "Other"]
CITIES = ["Astana, Kazakhstan", "Astanajapura, West Java, Indonesia",
          "Astana, Banten, Indonesia", "Astana, Cusco, Peru"]


def test_a_short_list_is_answered_without_typing(page):
    """Список из десятка вариантов рисуется по клику целиком — искать в нём надо
    среди СВОИХ вариантов, а не среди тех, что уже лежат на странице."""
    build(page, gh_select("degree--0", "Degree", DEGREES))
    assert fill_combobox(page, box(page, "degree--0"), "Master's Degree") is True
    assert combobox_value(page, box(page, "degree--0")) == "Master's Degree"


def test_the_phone_country_list_is_not_our_dropdown(page):
    """Тот самый сбой прогона 2026-08-24.

    Прежний `_fill_typeahead` брал `page.locator("[role=option]").first` по всей
    странице. На каждой форме Greenhouse рядом с полем «Phone» висит скрытый
    список intl-tel-input из 244 стран, и первым вариантом там всегда
    «Afghanistan +93». Клик уходил в него: на скрытом элементе он ждал видимости
    до таймаута, падал, и обязательное поле объявлялось незаполненным.
    """
    build(page, gh_select("candidate-location", "Location (City)", CITIES))
    assert page.locator("[role=option]").count() == 3      # чужие, из телефона
    assert fill_combobox(page, box(page, "candidate-location"), "Astana") is True
    assert combobox_value(page, box(page, "candidate-location")) == "Astana, Kazakhstan"


def test_the_choice_lands_in_the_form_not_only_on_screen(page):
    """react-select держит выбор ОТДЕЛЬНО от видимого текста: после выбора
    `input.value` снова пустой. Читать поле как текстовое — значит считать
    заполненное поле пустым, поэтому проверять надо по самой форме."""
    build(page, gh_select("degree--0", "Degree", DEGREES))
    twin = page.locator('input[aria-hidden="true"][required]')
    assert twin.count() == 1                                # пустой выбор ⇒ браузер ругается
    assert fill_combobox(page, box(page, "degree--0"), "High School") is True
    assert box(page, "degree--0").input_value() == ""       # в самом input по-прежнему пусто
    assert twin.count() == 0                                # служебный вход убран — выбор есть
    assert page.locator(".select__single-value").inner_text() == "High School"


def test_an_async_list_is_waited_for(page):
    """Список School/Location приходит с сервера. Замер 2026-08-24: у N26 варианты
    появились между 1.2 и 2.7 секунды после ввода — прежние фиксированные 1500 мс
    попадали в промежуток, когда своих вариантов ещё нет."""
    build(page, gh_select("school--0", "School",
                          ["Harvard University", "Harvey Mudd College"], async_ms=2200))
    assert fill_combobox(page, box(page, "school--0"), "Harvard University") is True
    assert combobox_value(page, box(page, "school--0")) == "Harvard University"


def test_stale_options_from_the_previous_query_are_not_clicked(page):
    """Пока ответ сервера в пути, в меню висят варианты прошлого запроса — на
    School это первая сотня вузов по алфавиту. Брать «первый вариант» нельзя:
    так в анкету попадает «3iL Limoges» вместо нужного вуза."""
    build(page, gh_select("school--0", "School",
                          ["3iL Limoges", "Aalborg University", "Harvard University"],
                          async_ms=1500))
    assert fill_combobox(page, box(page, "school--0"), "Harvard University") is True
    assert combobox_value(page, box(page, "school--0")) == "Harvard University"


def test_a_value_the_list_does_not_offer_is_a_failure(page):
    """Промах должен быть виден вызывающей стороне, а не замазан любым вариантом:
    случайный город в анкете хуже, чем честный ручной отклик."""
    build(page, gh_select("school--0", "School",
                          ["Harvard University", "Aalborg University"]))
    assert fill_combobox(page, box(page, "school--0"), "Nazarbayev University") is False
    assert combobox_value(page, box(page, "school--0")) == ""
    assert page.locator('input[aria-hidden="true"][required]').count() == 1


def test_punctuation_and_a_tail_in_the_option_do_not_block_the_match(page):
    """Замеры 2026-08-24: «Bachelors Degree» не находит «Bachelor's Degree» ни
    одним запросом целиком (у Greenhouse фильтр по подстроке), а вариант
    «Country» называется «Kazakhstan +7» — с телефонным кодом в тексте."""
    build(page,
          gh_select("degree--0", "Degree", DEGREES),
          gh_select("country", "Country", ["Kazakhstan +7", "Kenya +254"], shows="+7"))
    assert fill_combobox(page, box(page, "degree--0"), "Bachelors Degree") is True
    assert page.locator("#degree--0").evaluate(
        "e => e.closest('.select__value-container').innerText.trim()") == "Bachelor's Degree"
    # У страны на экране остаётся только код: название нарисовано флагом. Это
    # успех, а не промах, — значит сверять видимый текст с вариантом «в лоб» нельзя.
    assert fill_combobox(page, box(page, "country"), "Kazakhstan") is True
    assert combobox_value(page, box(page, "country")) == "+7"


def test_a_full_phrase_is_narrowed_down_to_the_option(page):
    """Живой замер: «Berlin, Germany» ищется целиком и даёт точное совпадение, а
    «Yes, I agree» в списке из «Yes»/«No» — нет. Сокращать запрос можно, ослаблять
    сверку с ответом — нельзя."""
    build(page, gh_select("q1", "I agree", ["Yes", "No"]))
    assert fill_combobox(page, box(page, "q1"), "Yes, I agree") is True
    assert combobox_value(page, box(page, "q1")) == "Yes"


def test_a_value_already_chosen_is_left_alone(page):
    """Повторный заход (форма перерисовалась, поле нашли заново) не должен
    открывать меню и выбирать заново. Список у поля для этого отбирается: ответ
    обязан засчитаться по тому, что в поле УЖЕ выбрано."""
    build(page, gh_select("degree--0", "Degree", DEGREES))
    assert fill_combobox(page, box(page, "degree--0"), "High School") is True
    box(page, "degree--0").evaluate("e => { e.dataset.options = '[]'; }")
    assert fill_combobox(page, box(page, "degree--0"), "High School") is True
    assert page.locator(".select__single-value").inner_text() == "High School"


def test_the_options_can_be_read_before_answering(page):
    """Скрапер видит react-select текстовым полем и приносит `options: []`,
    поэтому отвечает на такой вопрос вслепую. Замер на живой форме N26: вопрос
    про GDPR предлагает единственный вариант «I Acknowledge», и ответ «Yes» в
    него не попадает ничем. Значит, варианты надо уметь прочитать — не тронув
    поле."""
    build(page, gh_select("q1", "GDPR", ["I Acknowledge"]))
    assert combobox_options(page, box(page, "q1")) == ["I Acknowledge"]
    assert combobox_value(page, box(page, "q1")) == ""
    assert page.locator('input[aria-hidden="true"][required]').count() == 1
    assert combobox_options(page, page.locator('[data-af="нет-такого"]')) == []


def test_reading_the_options_leaves_the_field_ready_to_be_answered(page):
    """Два сбоя, пойманных на живых формах 2026-08-24 сразу после того, как
    появилось чтение вариантов. Прочитанный список оставался открытым и накрывал
    соседний вопрос — «End date month*» у Datadog после «Degree*» не открывался
    вовсе. А клик по уже открытому react-select его ЗАКРЫВАЕТ, и ответ его же
    собственным вариантом не проходил."""
    build(page, gh_select("degree--0", "Degree", DEGREES))
    options = combobox_options(page, box(page, "degree--0"))
    assert options == DEGREES
    assert page.locator("#react-select-degree--0-listbox").count() == 0
    assert fill_combobox(page, box(page, "degree--0"), options[1]) is True
    assert combobox_value(page, box(page, "degree--0")) == "Bachelor's Degree"


def test_a_list_already_open_is_not_toggled_shut(page):
    """То же самое с другой стороны: поле могли открыть до нас."""
    build(page, gh_select("degree--0", "Degree", DEGREES))
    box(page, "degree--0").click()
    assert box(page, "degree--0").get_attribute("aria-expanded") == "true"
    assert fill_combobox(page, box(page, "degree--0"), "High School") is True


def test_nothing_escapes_to_the_caller(page):
    """Наружу не должно лететь исключений: заполнение полей идёт в цикле, и
    сорвавшийся виджет обязан быть просто «не получилось»."""
    build(page, gh_select("degree--0", "Degree", DEGREES))
    assert fill_combobox(page, page.locator('[data-af="нет-такого"]'), "Что угодно") is False
    assert combobox_value(page, page.locator('[data-af="нет-такого"]')) == ""
    assert fill_combobox(page, box(page, "degree--0"), "") is False


def test_a_typeahead_that_keeps_its_text_in_the_input(page):
    """LinkedIn «Location (city)» — тот же контракт, но список лежит в конце
    body и связан с полем через `aria-owns`, а выбранное остаётся текстом в
    самом input. Поиск вариантов не должен зависеть от разметки Greenhouse."""
    page.set_content("""<body>
      <label for="loc">City</label>
      <input id="loc" data-af="loc" role="combobox" aria-autocomplete="list"
             aria-owns="loc-list" autocomplete="off">
      <div id="loc-list" role="listbox" style="display:none">
        <div role="option">Astana, Kazakhstan</div>
        <div role="option">Astara, Iran</div>
      </div>
      <script>
        const inp = document.getElementById('loc'), list = document.getElementById('loc-list');
        const show = () => { list.style.display = 'block'; };
        inp.addEventListener('click', show);
        inp.addEventListener('input', show);
        list.querySelectorAll('[role=option]').forEach(o =>
          o.addEventListener('click', () => {
            inp.value = o.textContent; list.style.display = 'none'; }));
      </script></body>""")
    assert fill_combobox(page, box(page, "loc"), "Astana") is True
    assert combobox_value(page, box(page, "loc")) == "Astana, Kazakhstan"


# --- живые формы -------------------------------------------------------------
# НИЧЕГО НЕ ОТПРАВЛЯЮТ: заполняют поле и читают, что в нём осталось.

@pytest.mark.live
@pytest.mark.parametrize("url,field,value,expect", [
    ("https://job-boards.greenhouse.io/embed/job_app?for=n26&token=7925103",
     "candidate-location", "Astana", "Astana, Kazakhstan"),
    ("https://job-boards.greenhouse.io/embed/job_app?for=datadog&token=8052095",
     "school--0", "Harvard University", "Harvard University"),
    ("https://job-boards.greenhouse.io/embed/job_app?for=datadog&token=8052095",
     "degree--0", "Bachelors Degree", "Bachelor's Degree"),
    ("https://job-boards.greenhouse.io/embed/job_app?for=datadog&token=8052095",
     "end-month--0", "June", "June"),
])
def test_live_greenhouse(url, field, value, expect):
    """Те самые поля, на которых встал прогон 2026-08-24."""
    pw = pytest.importorskip("patchright.sync_api")
    with pw.sync_playwright() as p:
        browser = p.chromium.launch(headless=True, channel="chrome")
        pg = browser.new_context().new_page()
        try:
            pg.goto(url, wait_until="domcontentloaded", timeout=60000)
            pg.wait_for_timeout(6000)
            pg.evaluate("(id) => document.getElementById(id).setAttribute('data-af', 'live')",
                        field)
            loc = pg.locator('[data-af="live"]')
            assert fill_combobox(pg, loc, value) is True
            assert combobox_value(pg, loc) == expect
        finally:
            browser.close()
