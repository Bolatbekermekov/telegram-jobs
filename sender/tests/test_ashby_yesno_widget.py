"""Пара кнопок `aria-pressed` вместо радиогруппы — виджет Ashby.

Живьём 2026-09-12, прогон по Indeed: три отклика на формы Ashby (Polymath,
Basis Research Institute, Blacksmith Agency) дошли до конца, нажали «Submit
Application» — и вернулись с «кнопка отправки нажата, но подтверждения не
видно — ВОЗМОЖНО, ЗАЯВКА УЖЕ УШЛА, проверь почту».

Снимок страницы, сохранённый тем же кодом, показал, что заявка НЕ ушла: форма
осталась на месте вместе с кнопкой отправки, резюме приложено, почта заполнена,
а обязательный вопрос «Do you require visa sponsorship?*» не отвечен — обе
кнопки несут `aria-pressed="false"`.

Причина в разметке. Это не `input[type=radio]`, который умеет `choice.py`, и не
скрытый чекбокс с `<label for>`, который он умеет тоже:

    <label class="… _required_f7cvd_91 …" for="ID">Do you require visa sponsorship?</label>
    <div class="… ashby-application-form-input-yesno">
      <button aria-pressed="false" data-option="yes">Yes</button>
      <button aria-pressed="false" data-option="no">No</button>
      <input type="checkbox" tabindex="-1" name="ID">
    </div>

Состояние держат КНОПКИ, а чекбокс рядом — то, что уедет в FormData. Скрапер
видел только чекбокс: один безымянный бинарный флажок вместо вопроса с двумя
вариантами. Ответить на него было нечем, и вопрос молча оставался пустым.

Цена ошибки двойная. Заявка не уходит — и отчёт вместо «не отвечено
обязательное поле» говорит «возможно, ушла, проверь почту», то есть посылает
человека искать письмо, которого не будет, и отговаривает подать заново.

Браузер настоящий, сеть не нужна: разметка подаётся через `set_content`, как в
`test_choice_widget.py`. Ничего никуда не отправляется.
"""
import pytest

from app.infrastructure.channels.external_apply import scrape_form
from app.infrastructure.widgets.choice import pick_choice_reason


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


# Снято с сохранённой страницы Polymath (jobs.ashbyhq.com), лид #1148: классы,
# порядок узлов, `tabindex="-1"` и ОТСУТСТВИЕ `type` у кнопок — как у площадки.
# Последнее не мелочь: без `type` кнопка внутри формы это submit, и живой
# обработчик Ashby гасит событие сам — здесь то же сделано руками.
#
# `display:none` на чекбоксе — не украшение, а суть задачи. На живой странице
# его прячет класс `_input_1svni_78`; замер сохранённой страницы дал
# `display: none` и `getClientRects().length === 0`. Значит фильтр видимости
# скрапера отсеивает чекбокс ДО всякого разбора, и опираться на него нельзя —
# зацепкой обязаны быть КНОПКИ. Первая версия этого теста стилей не ставила,
# проходила зелёным, а живой прогон всё равно оставлял вопрос без ответа:
# проверялась разметка, которой на площадке нет.
#
# Живая кнопка меняет `aria-pressed` и чекбокс через React; здесь тот же
# обработчик написан руками, иначе тест проверял бы вёрстку, а не то, что
# ответ ЗАСЧИТАН.
ASHBY_YESNO = """
<form>
  <div class="_fieldEntry_1e3gg_28 ashby-application-form-field-entry"
       data-field-path="9f467db3-74b5-409a-a6e5-5fe93f0d3e8d">
    <label class="_heading_f7cvd_52 _required_f7cvd_91 ashby-application-form-question-title"
           for="visa">Do you require visa sponsorship?</label>
    <div class="_container_1svni_28 _yesno_1e3gg_148 ashby-application-form-input-yesno">
      <button class="_option_1svni_32 ashby-application-form-input-yesno-option"
              aria-pressed="false" data-option="yes">Yes</button>
      <button class="_option_1svni_32 ashby-application-form-input-yesno-option"
              aria-pressed="false" data-option="no">No</button>
      <input type="checkbox" class="_input_1svni_78" tabindex="-1" name="visa" id="visa"
             style="display:none">
    </div>
  </div>
</form>
<script>
document.querySelectorAll('.ashby-application-form-input-yesno').forEach(g => {
  const box = g.querySelector('input[type=checkbox]');
  g.querySelectorAll('button[data-option]').forEach(b => {
    b.addEventListener('click', ev => {
      ev.preventDefault();   // у живой кнопки нет type, внутри формы это submit
      g.querySelectorAll('button[data-option]').forEach(
        o => o.setAttribute('aria-pressed', String(o === b)));
      box.checked = b.dataset.option === 'yes';
      box.value = b.dataset.option;
    });
  });
});
</script>
"""


def show(page, html):
    page.set_content(f"<body>{html}</body>")


def pressed(page):
    """Какой вариант отмечен — так, как это видит страница."""
    return page.evaluate(
        """() => [...document.querySelectorAll('button[data-option]')]
                    .filter(b => b.getAttribute('aria-pressed') === 'true')
                    .map(b => b.dataset.option)""")


def test_the_scraper_sees_a_question_with_two_options(page):
    """Пока скрапер видит безымянный чекбокс, отвечать нечему."""
    show(page, ASHBY_YESNO)
    fields = scrape_form(page).fields
    visa = [f for f in fields if "sponsorship" in (f.label or "").lower()]
    assert visa, f"вопрос про визу не найден вовсе; поля: {[f.label for f in fields]}"
    assert [o.lower() for o in visa[0].options] == ["yes", "no"], \
        f"варианты не распознаны: {visa[0].options!r}"


def test_the_scraper_marks_it_required(page):
    """Метка несёт класс `_required_`, звёздочка рисуется стилем — текста нет."""
    show(page, ASHBY_YESNO)
    visa = [f for f in scrape_form(page).fields
            if "sponsorship" in (f.label or "").lower()]
    assert visa and visa[0].required


def test_answering_no_is_registered_by_the_page(page):
    show(page, ASHBY_YESNO)
    visa = [f for f in scrape_form(page).fields
            if "sponsorship" in (f.label or "").lower()][0]
    ok, why = pick_choice_reason(page, page.locator(f'[data-af="{visa.ref}"]'), "No")
    assert ok, f"ответ не засчитан: {why}"
    assert pressed(page) == ["no"]


def test_answering_yes_is_registered_by_the_page(page):
    show(page, ASHBY_YESNO)
    visa = [f for f in scrape_form(page).fields
            if "sponsorship" in (f.label or "").lower()][0]
    ok, why = pick_choice_reason(page, page.locator(f'[data-af="{visa.ref}"]'), "Yes")
    assert ok, f"ответ не засчитан: {why}"
    assert pressed(page) == ["yes"]


# Перерисовка после клика — яма, в которую этот виджет уже падал. Живьём
# 2026-09-03, лид #800 (LinkedIn): React заменил ветку, по которой пришёл клик,
# наша пометка осталась на выброшенном узле, проверка не нашла ничего, и отчёт
# сказал «клик прошёл, но страница ответ не засчитала» при ПРИНЯТОМ ответе.
# Для radio и checkbox опорой служат `name`/`id`/текст блока; у кнопок Ashby нет
# ни имени, ни id, поэтому переиск должен уметь найти их заново.
ASHBY_YESNO_REMOUNTING = ASHBY_YESNO.replace(
    "box.value = b.dataset.option;",
    """box.value = b.dataset.option;
      // React на месте: вся группа заменяется новыми узлами с тем же видом.
      const box2 = g.cloneNode(true);
      // ...и БЕЗ наших пометок. `cloneNode` копирует атрибуты, а React рисует
      // узлы из своего дерева и о `data-af-pick` не знает — без этой строки
      // подделка сохраняла бы пометку и тест проходил бы по ложной причине,
      // ничего не проверяя. Ровно на этом обожглись на лиде #800.
      box2.querySelectorAll('[data-af-pick],[data-af-pick-label],[data-af]').forEach(
        e => { e.removeAttribute('data-af-pick');
               e.removeAttribute('data-af-pick-label');
               e.removeAttribute('data-af'); });
      g.parentNode.replaceChild(box2, g);
      wire(box2);""",
).replace(
    "document.querySelectorAll('.ashby-application-form-input-yesno').forEach(g => {",
    """function wire(g) {""",
).replace(
    """      box.value = b.dataset.option;""",
    """      box.value = b.dataset.option;""",
).replace("""});
</script>""", """}
document.querySelectorAll('.ashby-application-form-input-yesno').forEach(wire);
</script>""")


def test_the_answer_survives_the_form_redrawing_itself(page):
    show(page, ASHBY_YESNO_REMOUNTING)
    visa = [f for f in scrape_form(page).fields
            if "sponsorship" in (f.label or "").lower()][0]
    ok, why = pick_choice_reason(page, page.locator(f'[data-af="{visa.ref}"]'), "No")
    assert pressed(page) == ["no"], "ответ не дошёл до страницы вовсе"
    assert ok, f"ответ принят страницей, но признан непринятым: {why}"
