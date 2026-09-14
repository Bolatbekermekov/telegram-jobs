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


def test_a_place_lever_does_not_know_is_named_not_typed(page):
    from app.domain.channel import ManualApplyRequired
    from app.infrastructure.channels import external_apply as ea

    page.set_content(LEVER_LOCATION)
    with pytest.raises(ManualApplyRequired, match="Current location"):
        ea.fill_fields(page, _plan("Nowhere, Atlantis"))
