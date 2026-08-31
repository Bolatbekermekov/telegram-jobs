"""Ответ на вопрос с вариантами — на разметке, снятой с живой формы Recruitee.

Прогон 2026-08-24, лид #418: форма `jobs.profitap.com/o/qa-engineer-3/c/new`
заполнилась именем, почтой, телефоном и резюме и встала на
«Do you require visa sponsorship? *» — «не смог заполнить обязательное поле».

Замер показал, в чём дело. Настоящие `input[type=radio]` там ЕСТЬ (скрапер их
видит правильно: один вопрос, options ["Yes","No"], required), но спрятаны
классическим приёмом «visually hidden»:

    position:absolute; width:1px; height:1px; clip:rect(0,0,0,0);
    margin:-1px; padding:0; border:0; overflow:hidden; white-space:nowrap

`fill_fields` жмёт по такой кнопке `check(force=True)` — настоящий клик мышью в
центр этого прямоугольника 1×1. В headless он почему-то доходит, а в headed —
а прогон идёт именно headed, `BROWSER_HEADLESS` по умолчанию `false` — нет:

    Locator.check: Clicking the checkbox did not change its state
      - forcing action
      - performing click action
      - click action done

Состояние не изменилось, Playwright бросает, обязательное поле → ручной отклик.
Хуже того, `click(force=True)` на той же кнопке НЕ бросает ничего и тоже ничего
не выбирает — то есть «починка» кликом молча оставила бы вопрос без ответа.

Браузер настоящий, но сеть не нужна: разметка подаётся через `set_content`,
как в `test_scrape_form.py`. Живой прогон по настоящей форме — под меткой
`live`, и он НИЧЕГО НЕ ОТПРАВЛЯЕТ.
"""
import pytest

from app.infrastructure.channels.external_apply import scrape_form
from app.infrastructure.widgets.choice import pick_choice, pick_choice_reason


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


def show(page, html):
    page.set_content(f"<body>{html}</body>")


def af(page, ref):
    """Локатор контрола так, как его получает `fill_fields`: по метке скрапера."""
    return page.locator(f'[data-af="{ref}"]')


def checked(page, name):
    """Какие кнопки группы отмечены — по value, как их видит браузер."""
    return page.evaluate(
        """(n) => [...document.querySelectorAll('[name="'+n+'"]')]
                    .filter(e => e.checked).map(e => e.value)""", name)


def form_data(page):
    """ДАННЫЕ формы, а не её вид: то, что уедет работодателю."""
    return page.evaluate("""() => {
        const f = document.querySelector('form');
        return f ? [...new FormData(f).entries()] : [];
    }""")


# --- живая разметка Recruitee -------------------------------------------------
# Снято 2026-08-24 с https://jobs.profitap.com/o/qa-engineer-3/c/new. Классы
# styled-components заменены на говорящее имя, всё остальное — как на странице:
# скрытый `openQuestionId`, `legend` с вопросом, два настоящих radio с
# value="true"/"false" и метка, которая и есть видимая кнопка.
_HIDDEN = ("position:absolute;width:1px;height:1px;clip:rect(0,0,0,0);"
           "margin:-1px;padding:0;border:0;overflow:hidden;white-space:nowrap")

VISA = "candidate.openQuestionAnswers.6703065.flag"
RELOCATE = "candidate.openQuestionAnswers.6703066.flag"


def _question(qid, name, text, style=_HIDDEN):
    return f"""
    <div>
      <input type="hidden" value="{qid}" name="candidate.openQuestionAnswers.{qid}.openQuestionId">
      <div><fieldset>
        <legend>{text}<span aria-hidden="true">&nbsp;<span
           title="This field is required and can not be left empty.">*</span></span></legend>
        <div>
          <div><input type="radio" required aria-invalid="false" id="in-{qid}-0"
                      value="true" name="{name}" style="{style}"><label
                      for="in-{qid}-0"><span></span><span>Yes</span></label></div>
          <div><input type="radio" required aria-invalid="false" id="in-{qid}-1"
                      value="false" name="{name}" style="{style}"><label
                      for="in-{qid}-1"><span></span><span>No</span></label></div>
        </div>
      </fieldset><div role="alert" id="in-{qid}-error"></div></div>
    </div>"""


RECRUITEE = f"""
<form>
  <fieldset><legend>Questions</legend>
    <label for="name">Full name *</label>
    <input type="text" id="name" name="candidate.name" required>
    {_question(6703065, VISA, "Do you require visa sponsorship?")}
    {_question(6703066, RELOCATE, "Are you open to relocating to the Eindhoven Area? (The Netherlands)")}
  </fieldset>
</form>"""


def test_it_answers_a_radio_hidden_behind_a_styled_label(page):
    """Тот самый вопрос лида #418. `check(force=True)` в headed до этой кнопки не
    достучался — «Clicking the checkbox did not change its state»."""
    show(page, RECRUITEE)
    obs = scrape_form(page)
    visa = next(f for f in obs.fields if f.name == VISA)
    assert visa.options == ["Yes", "No"]          # скрапер вопрос видит верно

    assert pick_choice(page, af(page, visa.ref), value="No", index=1) is True
    assert checked(page, VISA) == ["false"]


def test_the_answer_lands_in_the_form_data_not_only_in_the_view(page):
    """Отметить кнопку мало: работодателю уезжают ДАННЫЕ формы. До ответа записи
    про этот вопрос в `FormData` нет вовсе — она должна появиться."""
    show(page, RECRUITEE)
    assert not [v for k, v in form_data(page) if k == VISA]

    visa = next(f for f in scrape_form(page).fields if f.name == VISA)
    assert pick_choice(page, af(page, visa.ref), value="No", index=1) is True
    assert [v for k, v in form_data(page) if k == VISA] == ["false"]


def test_every_choice_question_on_the_form_is_answerable(page):
    """Правило про один вопрос — не правило. На этой же форме рядом стоит
    «Are you open to relocating…», собранная точно так же."""
    show(page, RECRUITEE)
    fields = {f.name: f for f in scrape_form(page).fields}
    assert pick_choice(page, af(page, fields[VISA].ref), value="No", index=1) is True
    assert pick_choice(page, af(page, fields[RELOCATE].ref), value="Yes", index=0) is True
    assert dict(form_data(page))[VISA] == "false"
    assert dict(form_data(page))[RELOCATE] == "true"


def test_the_index_means_what_the_scraper_meant(page):
    """План хранит НОМЕР варианта из `options` скрапера. Виджет обязан считать
    группу тем же способом (`input[type=X]` с тем же `name`, в порядке
    документа), иначе номер укажет на чужую кнопку."""
    show(page, RECRUITEE)
    visa = next(f for f in scrape_form(page).fields if f.name == VISA)
    idx = visa.options.index("No")
    assert pick_choice(page, af(page, visa.ref), index=idx) is True
    assert page.evaluate(
        """() => document.querySelector('[name="%s"]:checked')
                   .labels[0].textContent.trim()""" % VISA) == "No"


def test_an_overlay_over_the_control_does_not_stop_the_answer(page):
    """Ровно тот сбой, что убил лид #418, но воспроизводимый в headless: клик
    мышью до кнопки не доходит. `check(force=True)` здесь отвечает тем же
    «Clicking the checkbox did not change its state», а клик по метке —
    таймаутом. Ответ всё равно должен быть записан."""
    show(page, f"""
      <form><fieldset style="position:relative"><legend>Do you require visa sponsorship?</legend>
        <div style="position:absolute;inset:0;background:#fff;z-index:99"></div>
        <div><input type="radio" id="y" name="{VISA}" value="true"
             style="{_HIDDEN}"><label for="y">Yes</label></div>
        <div><input type="radio" id="n" name="{VISA}" value="false"
             style="{_HIDDEN}"><label for="n">No</label></div>
      </fieldset></form>""")
    visa = next(f for f in scrape_form(page).fields if f.name == VISA)
    assert pick_choice(page, af(page, visa.ref), value="No", index=1) is True
    assert dict(form_data(page))[VISA] == "false"


def test_a_control_the_page_never_lays_out_is_still_answerable(page):
    """`display:none` на обёртке: у кнопки нет ни размера, ни точки клика, и
    Playwright отказывается («Element is not visible» / «outside of the
    viewport»). Так рисуют ветки формы, которые открываются ответом выше."""
    show(page, f"""
      <form><fieldset><legend>Do you require visa sponsorship?</legend>
        <div style="display:none">
          <label><input type="radio" name="{VISA}" value="true">Yes</label>
          <label><input type="radio" name="{VISA}" value="false">No</label>
        </div>
      </fieldset></form>""")
    # Скрапер такую кнопку не отдаёт (она невидима) — локатор берём напрямую,
    # как его получит вызывающая сторона после перерисовки формы.
    loc = page.locator(f'input[name="{VISA}"]').first
    assert pick_choice(page, loc, value="No", index=1) is True
    assert dict(form_data(page))[VISA] == "false"


def test_an_option_can_be_named_instead_of_numbered(page):
    """Номера может не быть: `_yes_no` возвращает голое «No», когда вариантов
    не нашлось. Тогда вариант ищется по подписи."""
    show(page, RECRUITEE)
    visa = next(f for f in scrape_form(page).fields if f.name == VISA)
    assert pick_choice(page, af(page, visa.ref), value="No") is True
    assert checked(page, VISA) == ["false"]


def test_no_is_not_answered_with_not_sure(page):
    """«No» — подстрока «Not sure» и «No experience». Совпадение по подстроке
    ответило бы на вопрос не тем, что решил план, и заметить это некому."""
    show(page, """
      <form><fieldset><legend>Do you require visa sponsorship?</legend>
        <label><input type="radio" name="q" value="1">Not sure</label>
        <label><input type="radio" name="q" value="2">No</label>
        <label><input type="radio" name="q" value="3">Yes</label>
      </fieldset></form>""")
    assert pick_choice(page, page.locator('input[name="q"]').first, value="No") is True
    assert checked(page, "q") == ["2"]


def test_a_checkbox_group_is_answered_the_same_way(page):
    """Lever задаёт вопрос с вариантами набором чекбоксов под одним `name` —
    скрапер уже собирает их в один вопрос, отвечать на них тоже нужно."""
    show(page, """
      <form><div class="application-question">
        <div class="text">Which React versions have you worked with?</div>
        <ul>
          <li><label><input type="checkbox" name="cards[abc][values]" value="16" required> React 16 or earlier</label></li>
          <li><label><input type="checkbox" name="cards[abc][values]" value="18" required> React 18+</label></li>
        </ul>
      </div></form>""")
    f = scrape_form(page).fields[0]
    assert f.options == ["React 16 or earlier", "React 18+"]
    assert pick_choice(page, af(page, f.ref), index=1) is True
    assert dict(form_data(page))["cards[abc][values]"] == "18"


def test_a_lone_consent_box_is_ticked_the_same_way(page):
    """Согласие — не вопрос с вариантами, но прячут его тем же приёмом, и
    `fill_fields` жмёт по нему тем же `check(force=True)`, который в headed не
    сработал на Recruitee. Группа из одного — вариант с номером 0."""
    show(page, f"""
      <form><p>Acme has my consent to process my data*</p>
        <input type="checkbox" id="c" name="consent" value="true" style="{_HIDDEN}">
        <label for="c"><span></span><span>Yes</span></label></form>""")
    f = scrape_form(page).fields[0]
    assert f.options == []                       # одиночная галочка, не группа
    assert pick_choice(page, af(page, f.ref), index=0) is True
    assert dict(form_data(page))["consent"] == "true"


def test_an_already_chosen_option_is_left_alone(page):
    """Клик по уже отмеченному ЧЕКБОКСУ снимает галочку. Если форма приехала с
    готовым ответом (или ответ поставили выше по коду), виджет обязан оставить
    его, а не переключить в противоположный."""
    show(page, """
      <form>
        <label><input type="checkbox" name="q" value="a" checked> Alpha</label>
        <label><input type="checkbox" name="q" value="b"> Beta</label>
      </form>""")
    assert pick_choice(page, page.locator('input[name="q"]').first,
                       value="Alpha", index=0) is True
    assert checked(page, "q") == ["a"]


def test_a_control_that_refuses_the_answer_reports_failure(page):
    """Молчаливое «получилось» страшнее отказа: заявка уйдёт с вопросом без
    ответа, и никто об этом не узнает. Страница, отменяющая клик, должна дать
    False — вызывающая сторона отправит лид в ручной отклик."""
    show(page, f"""
      <form><fieldset><legend>Do you require visa sponsorship?</legend>
        <label><input type="radio" name="{VISA}" value="true">Yes</label>
        <label><input type="radio" name="{VISA}" value="false">No</label>
      </fieldset></form>
      <script>document.querySelectorAll('input[type=radio]').forEach(
        e => e.addEventListener('click', ev => ev.preventDefault()));</script>""")
    loc = page.locator(f'input[name="{VISA}"]').first
    assert pick_choice(page, loc, value="No", index=1) is False
    assert checked(page, VISA) == []


def test_a_disabled_control_is_a_refusal_not_a_tick(page):
    """Выключенная кнопка в данные формы не попадает, сколько по ней ни бей."""
    show(page, f"""
      <form><fieldset><legend>Do you require visa sponsorship?</legend>
        <label><input type="radio" name="{VISA}" value="true" disabled>Yes</label>
        <label><input type="radio" name="{VISA}" value="false" disabled>No</label>
      </fieldset></form>""")
    loc = page.locator(f'input[name="{VISA}"]').first
    assert pick_choice(page, loc, value="No", index=1) is False
    assert dict(form_data(page)) == {}


def test_it_returns_false_instead_of_raising_when_the_control_is_gone(page):
    """Форму могло перерисовать между планом и заполнением. Исключение отсюда
    затёрло бы диагноз в `fill_fields` — наружу выходит только False."""
    show(page, "<form></form>")
    assert pick_choice(page, page.locator('[data-af="7"]'), value="No", index=1) is False


def test_an_index_out_of_range_is_a_refusal_not_a_crash(page):
    show(page, RECRUITEE)
    visa = next(f for f in scrape_form(page).fields if f.name == VISA)
    assert pick_choice(page, af(page, visa.ref), index=9) is False
    assert pick_choice(page, af(page, visa.ref), value="Maybe") is False
    assert checked(page, VISA) == []


def test_an_option_drawn_without_a_real_input(page):
    """Часть форм рисует варианты одними div-ами с `role=radio`; выбор там
    виден только по `aria-checked`. Скрапер такие не отдаёт, но локатор может
    прийти и снаружи, и «получилось» по `checked` у div-а не проверить."""
    show(page, """
      <div role="radiogroup" aria-label="Do you require visa sponsorship?">
        <div role="radio" aria-checked="false" id="r0">Yes</div>
        <div role="radio" aria-checked="false" id="r1">No</div>
      </div>
      <script>document.querySelectorAll('[role=radio]').forEach(e =>
        e.addEventListener('click', () => {
          document.querySelectorAll('[role=radio]').forEach(
            x => x.setAttribute('aria-checked', String(x === e)));
        }));</script>""")
    assert pick_choice(page, page.locator("#r0"), value="No", index=1) is True
    assert page.get_attribute("#r1", "aria-checked") == "true"


@pytest.mark.live
def test_live_recruitee_form_headed():
    """Живой прогон по форме лида #418 в headed — том режиме, в котором она и
    сорвалась (`BROWSER_HEADLESS` по умолчанию `false`, а в headless сбой не
    воспроизводится). НИЧЕГО НЕ ОТПРАВЛЯЕТ: жмём только по вариантам."""
    pw = pytest.importorskip("patchright.sync_api")
    url = "https://jobs.profitap.com/o/qa-engineer-3/c/new"
    with pw.sync_playwright() as p:
        browser = p.chromium.launch(headless=False, channel="chrome")
        live = browser.new_context().new_page()
        try:
            live.goto(url, wait_until="domcontentloaded", timeout=60000)
            live.wait_for_timeout(4000)
            fields = {f.name: f for f in scrape_form(live).fields}
            for name, want, idx in ((VISA, "No", 1), (RELOCATE, "Yes", 0)):
                assert pick_choice(live, af(live, fields[name].ref),
                                   value=want, index=idx) is True
            data = dict(form_data(live))
            assert data[VISA] == "false" and data[RELOCATE] == "true"
        finally:
            browser.close()


# --- отказ обязан называть причину -------------------------------------------
#
# Живьём 2026-08-29 отказ «не выбрался вариант «Yes»» пришёл ЧЕТЫРЕ раза за один
# прогон на LinkedIn Easy Apply («Do you have experience with GO?», «valid
# driver\'s license», «comfortable commuting»), и разобрать его было нечем: за
# одной фразой стоят четыре разных случая, и чинятся они по-разному.

_YESNO = """
  <form><fieldset>
    <legend>Do you have experience with GO?</legend>
    <label for="q-0"><input type="radio" id="q-0" data-af="0" name="q" value="Yes">Yes</label>
    <label for="q-1"><input type="radio" id="q-1" name="q" value="No">No</label>
  </fieldset></form>
"""


def test_a_missing_option_says_so(page):
    show(page, _YESNO)
    ok, why = pick_choice_reason(page, af(page, "0"), value="Maybe", index=None)

    assert ok is False
    assert "нет среди кнопок группы" in why


def test_a_disabled_control_says_so(page):
    show(page, _YESNO.replace('id="q-0"', 'id="q-0" disabled'))
    ok, why = pick_choice_reason(page, af(page, "0"), value="Yes", index=0)

    assert ok is False
    assert "выключенным" in why
    assert checked(page, "q") == []          # выключенное не жмём вовсе


def test_a_working_pick_carries_no_reason(page):
    show(page, _YESNO)
    assert pick_choice_reason(page, af(page, "0"), value="Yes", index=0) == (True, "")
    assert checked(page, "q") == ["Yes"]


def test_a_pick_the_page_undoes_lists_what_was_tried(page):
    """Все три способа отработали, а состояние не изменилось — самый частый случай.

    Разметка тут нарочно враждебная: обработчик снимает выбор сразу после любого
    клика, ровно как ведёт себя форма, которая ответ не принимает.
    """
    show(page, _YESNO + """
      <script>document.querySelectorAll('input[name=q]').forEach(
        e => e.addEventListener('click', () => { e.checked = false; }));</script>
    """)
    ok, why = pick_choice_reason(page, af(page, "0"), value="Yes", index=0)

    assert ok is False
    assert "страница ответ не засчитала" in why
    assert "native_click" in why and "force_check" in why


def test_the_plain_wrapper_still_returns_a_bool(page):
    show(page, _YESNO)
    assert pick_choice(page, af(page, "0"), value="Yes", index=0) is True
