"""Ashby сам разбирает загруженное резюме и заполняет поля — отправка попадает
в этот промежуток.

Живьём 2026-09-17, два лида подряд: #1411 (jobs.ashbyhq.com/makai-labs) —
«Your form needs corrections. Missing entry for required field: Email. Missing
entry for required field: Location»; #1431 (jobs.ashbyhq.com/bjakcareer) — то же
самое, но пустыми названы Phone number и Consent. Поля каждый раз РАЗНЫЕ: это
гонка, а не пробел в сопоставлении.

В дампе #1411 видно и причину, и признак: наши значения в разметке стоят
(`_systemfield_name` = «Bolatbek Yermekov», `_systemfield_email` заполнен), а над
списком ошибок висит слой «Parsing your resume. Autofilling key fields...».

Разметка и стили ниже сняты оттуда же: сам слой — из дампа, два правила CSS — из
таблицы стилей Ashby (`index-CDkhpK5Z.css`), потому что без них слой не
скрывается и проверка «ждём только пока он виден» ничего бы не значила. Из CSS
же видно, ЧЕМ отличается работающее автозаполнение: `data-state=active` — это
единственное состояние, в котором слой показывается.
"""
import time

import pytest

from app.application.auto_apply import ApplyPlan, FillAction
from app.domain.page_observation import FieldObs


@pytest.fixture(scope="module")
def page():
    pw = pytest.importorskip("patchright.sync_api")
    try:
        p = pw.sync_playwright().start()
        browser = p.chromium.launch(headless=True, channel="chrome")
    except Exception as exc:  # noqa: BLE001 — без Chrome тест не запускается
        pytest.skip(f"нет браузера: {type(exc).__name__}")
    pg = browser.new_context().new_page()
    yield pg
    browser.close()
    p.stop()


# Два правила из живой таблицы стилей Ashby — слой скрыт, пока состояние не
# `active`.
ASHBY_CSS = """<style>
._pending_xd2v0_121{opacity:0;pointer-events:none;visibility:hidden;display:flex;
  position:absolute;top:0;bottom:0;left:0;right:0}
._pending_xd2v0_121[data-state=active]{opacity:1;pointer-events:all;visibility:visible}
</style>"""

# Слой автозаполнения — как он лежит в дампе #1411.
PENDING = """<div class="_pending_xd2v0_121 ashby-application-form-autofill-input-pending-layer"
     data-state="{state}"><span aria-label="Loading..." role="progressbar"
     class="_spinner_8ul1h_9 _spinner-size-md_8ul1h_26"></span><span>Parsing your resume. Autofilling key fields...</span></div>"""

# Поля из дампа #1411, слово в слово.
FIELDS = """
<div class="_fieldEntry_1e3gg_28 ashby-application-form-field-entry"
     data-field-path="_systemfield_name">
  <label class="_heading_f7cvd_52 _required_f7cvd_91" for="_systemfield_name">Name</label>
  <div><input placeholder="Type here..." name="_systemfield_name" required="" id="_systemfield_name"
       type="text" class="_input_80epu_28 ashby-application-form-input-text"
       value="Bolatbek Yermekov" data-af="1"></div>
</div>
<div class="_fieldEntry_1e3gg_28 ashby-application-form-field-entry"
     data-field-path="_systemfield_email">
  <label class="_heading_f7cvd_52 _required_f7cvd_91" for="_systemfield_email">Email</label>
  <div><input placeholder="hello@example.com..." name="_systemfield_email" required=""
       id="_systemfield_email" type="email" class="_input_80epu_28 ashby-application-form-input-text"
       value="ermekovbolatbek50@gmail.com" data-af="2"></div>
</div>
<div class="_fieldEntry_1e3gg_28 ashby-application-form-field-entry"
     data-field-path="_systemfield_location">
  <label class="_heading_f7cvd_52 _required_f7cvd_91" for="_systemfield_location">Location</label>
  <div class="_inputContainer_d7ago_28">
    <input class="_input_d7ago_28 ashby-application-form-input-autocomplete"
           placeholder="Start typing..." aria-autocomplete="list" aria-expanded="false"
           aria-haspopup="listbox" role="combobox" value="Astana, Kazakhstan" data-af="5">
  </div>
</div>
"""


def _email_field():
    return FieldObs(tag="input", type="email", name="_systemfield_email", required=True,
                    ref="2", label="Email")


def _location_field():
    return FieldObs(tag="input", type="text", name="_systemfield_location", required=True,
                    ref="5", label="Location", combobox=True)


# --- ждём, пока Ashby дочитает резюме ----------------------------------------

def test_the_running_autofill_holds_the_form_until_it_finishes(page):
    """Пока слой показан, трогать форму нельзя: всё набранное будет затёрто."""
    from app.infrastructure.channels import external_apply as ea

    page.set_content(ASHBY_CSS + PENDING.format(state="active") + FIELDS + """
    <script>setTimeout(() => {
      document.querySelector('[data-state]').setAttribute('data-state', 'hidden');
      document.getElementById('_systemfield_email').value = '';
    }, 700);</script>""")

    started = time.monotonic()
    ea._wait_for_autofill(page)
    waited = time.monotonic() - started

    assert waited >= 0.6, "отправка ушла прямо в разбор резюме"
    assert page.get_attribute("[data-state]", "data-state") == "hidden"


def test_a_finished_autofill_does_not_hold_the_form(page):
    """Слой лежит в разметке ВСЕГДА — в дампе #1411 он с `data-state="hidden"`.

    Если ждать просто текста про parsing, каждая форма Ashby будет стоять до
    потолка ожидания на ровном месте.
    """
    from app.infrastructure.channels import external_apply as ea

    page.set_content(ASHBY_CSS + PENDING.format(state="hidden") + FIELDS)

    started = time.monotonic()
    ea._wait_for_autofill(page)

    assert time.monotonic() - started < 1.5, "ждём несуществующее автозаполнение"


def test_the_autofill_is_given_a_moment_to_start_after_the_upload(page):
    """Разбор начинается НЕ мгновенно: сразу после загрузки резюме слой ещё
    `hidden`, и проверка «работает ли автозаполнение» в эту секунду отвечает
    «нет». Живая таблица стилей добавляет к этому переход `transition:all .1s`,
    из-за которого только что показанный слой ещё сотую долю секунды числится
    скрытым. Поэтому после загрузки слою дают время начаться.
    """
    from app.infrastructure.channels import external_apply as ea

    page.set_content(ASHBY_CSS + PENDING.format(state="hidden") + FIELDS + """
    <script>
      const layer = document.querySelector('[data-state]');
      setTimeout(() => layer.setAttribute('data-state', 'active'), 300);
      setTimeout(() => layer.setAttribute('data-state', 'hidden'), 1100);
    </script>""")

    started = time.monotonic()
    ea._wait_for_autofill(page, grace_ms=2000)
    waited = time.monotonic() - started

    assert waited >= 1.0, "не дождались разбора, который ещё не успел начаться"
    assert waited < 4, "ждём дольше самого разбора"


def test_a_form_without_the_autofill_layer_is_not_waited_for(page):
    """Форму без разбора резюме ожидание не задерживает — даже с отсрочкой:
    ждать нечего, слоя в разметке нет вовсе."""
    from app.infrastructure.channels import external_apply as ea

    page.set_content(ASHBY_CSS + FIELDS)

    started = time.monotonic()
    ea._wait_for_autofill(page, grace_ms=2000)

    assert time.monotonic() - started < 1.5


# --- подтверждаем то, что автозаполнение успело затереть ----------------------

def test_a_text_field_wiped_by_the_autofill_is_typed_again(page):
    """«Missing entry for required field: Email» — поле было опустошено уже после
    того, как мы его заполнили."""
    from app.infrastructure.channels import external_apply as ea

    page.set_content(ASHBY_CSS + PENDING.format(state="hidden") + FIELDS)
    page.eval_on_selector("#_systemfield_email", "el => el.value = ''")
    plan = ApplyPlan(actions=[FillAction(field=_email_field(),
                                         value="ermekovbolatbek50@gmail.com",
                                         source="profile")])

    ea._reassert_text_values(page, plan)

    assert page.input_value("#_systemfield_email") == "ermekovbolatbek50@gmail.com"


def test_a_text_field_that_survived_is_left_alone(page):
    """Лишний `fill` по живому полю — лишний повод форме перерисоваться."""
    from app.infrastructure.channels import external_apply as ea

    page.set_content(ASHBY_CSS + PENDING.format(state="hidden") + FIELDS)
    typed = []
    page.expose_function("_noteFill", lambda: typed.append(1))
    page.eval_on_selector(
        "#_systemfield_email",
        "el => el.addEventListener('input', () => window._noteFill())")
    plan = ApplyPlan(actions=[FillAction(field=_email_field(),
                                         value="ermekovbolatbek50@gmail.com",
                                         source="profile")])

    ea._reassert_text_values(page, plan)

    assert typed == [], "поле переписано зря"


def test_the_location_is_picked_from_the_suggestions_again(page, monkeypatch):
    """Место — автодополнение (`role="combobox"`), и текст в нём формой не
    считается: в дампе #1411 стоит «Astana, Kazakhstan» при `aria-expanded="false"`,
    а форма отвечает «Missing entry for required field: Location».

    Тот же приём уже применён к Lever (`_reassert_lever_location`): проверять
    нечего — выбор делается заново. Разметку списка подсказок Ashby мы живьём не
    снимали, поэтому здесь проверяется именно РЕШЕНИЕ — что выбор запрашивается
    заново, а не пропускается из-за совпавшего текста.
    """
    from app.infrastructure.channels import external_apply as ea

    page.set_content(ASHBY_CSS + PENDING.format(state="hidden") + FIELDS)
    calls = []
    monkeypatch.setattr(ea, "_fill_combobox",
                        lambda pg, loc, value, **kw: calls.append((value, kw)) or True)
    plan = ApplyPlan(actions=[FillAction(field=_location_field(),
                                         value="Astana, Kazakhstan", source="profile")])

    ea._reassert_text_values(page, plan)

    assert calls, "место не выбиралось заново — форма его не увидит"
    assert calls[0][1].get("force"), \
        "совпавший текст не доказывает выбор: подсказку надо нажать заново"
