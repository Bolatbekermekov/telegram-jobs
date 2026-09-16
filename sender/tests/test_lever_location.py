"""Lever «Current location» берёт место только из своих подсказок.

Живьём 2026-09-14 (лид #1264, HighLevel на Lever): «Current location ✱» — это
`input#location-input` со скрытым `#selected-location`. Набранный текст без
выбора подсказки не считается: форма отказала в отправке с пустым `location`.
Снято там же: после «Astana» появляются `div.dropdown-location#location-0`
«Astana, KAZ» и `#location-1` «Astana, Panjshir, AFG».
"""
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


LEVER_LOCATION = """<body><form><ul><li data-qa="structured-contact-location-question"><label>
  <div>Current location <span>✱</span></div>
  <div>
    <input data-qa="location-input" id="location-input" type="text" maxlength="100"
           name="location" required data-af="0">
    <input id="selected-location" type="hidden" name="selectedLocation" value='{"name":""}'>
    <div id="drop" style="display: none;"><div id="results"></div></div>
  </div>
</label></li></ul></form>
<script>
(() => {
  const input = document.getElementById('location-input');
  const hidden = document.getElementById('selected-location');
  const drop = document.getElementById('drop');
  const results = document.getElementById('results');
  input.addEventListener('input', () => {
    hidden.value = '{"name":""}';
    results.innerHTML = '';
    if (!/^astana$/i.test(input.value.trim())) { drop.style.display = 'none'; return; }
    setTimeout(() => {
      ['Astana, Panjshir, AFG', 'Astana, KAZ'].forEach((name, i) => {
        const item = document.createElement('div');
        item.id = 'location-' + i;
        item.className = 'dropdown-location';
        item.textContent = name;
        item.addEventListener('click', () => {
          input.value = name;
          hidden.value = JSON.stringify({name});
          drop.style.display = 'none';
        });
        results.appendChild(item);
      });
      drop.style.display = 'flex';
    }, 400);
  });
})();
</script></body>"""


def _plan(value):
    field = FieldObs(tag="input", type="text", name="location", required=True, ref="0",
                     label="Current location ✱")
    return ApplyPlan(actions=[FillAction(field=field, value=value, source="profile")])


def test_the_location_is_chosen_from_levers_suggestions(page):
    from app.infrastructure.channels import external_apply as ea

    page.set_content(LEVER_LOCATION)
    ea.fill_fields(page, _plan("Astana, Kazakhstan"))

    assert page.input_value("#selected-location") == '{"name":"Astana, KAZ"}'
    assert page.input_value("#location-input") == "Astana, KAZ"


LEVER_SLOW_LOCATION = """<body><form><ul><li data-qa="structured-contact-location-question"><label>
  <div>Current location <span>✱</span></div>
  <div>
    <input data-qa="location-input" id="location-input" type="text" maxlength="100"
           name="location" required data-af="0">
    <input id="selected-location" type="hidden" name="selectedLocation" value='{"name":""}'>
    <div id="drop" style="display: none;"><div id="results"></div></div>
  </div>
</label></li></ul></form>
<script>
(() => {
  const input = document.getElementById('location-input');
  const hidden = document.getElementById('selected-location');
  const drop = document.getElementById('drop');
  const results = document.getElementById('results');
  const show = names => {
    results.innerHTML = '';
    names.forEach((name, i) => {
      const item = document.createElement('div');
      item.id = 'location-' + i;
      item.className = 'dropdown-location';
      item.textContent = name;
      item.addEventListener('click', () => {
        if (!name.includes(',')) return;      // заглушка выбором не становится
        input.value = name;
        hidden.value = JSON.stringify({name});
        drop.style.display = 'none';
      });
      results.appendChild(item);
    });
    drop.style.display = 'flex';
  };
  input.addEventListener('input', () => {
    hidden.value = '{"name":""}';
    if (!/^astana$/i.test(input.value.trim())) { drop.style.display = 'none'; return; }
    setTimeout(() => show(['No location found. Try entering a different location Loading']), 200);
    setTimeout(() => show(['Astana, Panjshir, AFG', 'Astana, KAZ']), 900);
  });
})();
</script></body>"""


def test_suggestions_that_are_still_loading_are_not_an_answer(page):
    """Живьём 2026-09-16 (лид #1316, XTB на Lever): в подписи отказа стояло и «No
    location found. Try entering a different location», и «Loading» — список
    прочитали, пока он ещё грузился, и заявка ушла в ручные. Ждать надо не
    появления списка, а настоящих подсказок."""
    from app.infrastructure.channels import external_apply as ea

    page.set_content(LEVER_SLOW_LOCATION)
    ea.fill_fields(page, _plan("Astana, Kazakhstan"))

    assert page.input_value("#selected-location") == '{"name":"Astana, KAZ"}'


def test_a_place_lever_does_not_know_is_named_not_typed(page):
    from app.domain.channel import ManualApplyRequired
    from app.infrastructure.channels import external_apply as ea

    page.set_content(LEVER_LOCATION)
    with pytest.raises(ManualApplyRequired, match="Current location"):
        ea.fill_fields(page, _plan("Nowhere, Atlantis"))


def test_a_location_the_form_forgot_is_picked_again_before_submit(page):
    """Живьём 2026-09-14 (#1264, прогон 7): место было выбрано, а к отправке
    скрытое `selectedLocation` снова пустое при тексте «Astana, KAZ» — форма
    перерисовалась, пока Lever разбирал резюме. Перед отправкой — выбрать снова."""
    from app.infrastructure.channels import external_apply as ea

    page.set_content(LEVER_LOCATION)
    plan = _plan("Astana, Kazakhstan")
    ea.fill_fields(page, plan)
    page.evaluate("() => { document.getElementById('selected-location').value = '{\"name\":\"\"}'; }")

    ea._reassert_lever_location(page, plan)

    assert page.input_value("#selected-location") == '{"name":"Astana, KAZ"}'


def test_the_lever_location_is_reasserted_before_the_submit_click(monkeypatch):
    from app.domain.page_observation import PageObservation
    from app.infrastructure.channels import external_apply as ea
    from tests.test_external_apply import FakePage

    page = FakePage(PageObservation(url="https://jobs.lever.co/x/apply"), present={ea.SEL_SUBMIT})
    monkeypatch.setattr(ea, "fill_fields", lambda page, plan, **kw: None)
    monkeypatch.setattr(ea, "_reassert_choices", lambda page, plan: None)
    monkeypatch.setattr(ea, "_reassert_lever_location",
                        lambda page, plan: page.clicks.append("lever-location"))

    ea.fill_and_submit(page, plan=None, dry_run=False)

    assert page.clicks == ["lever-location", ea.SEL_SUBMIT]
