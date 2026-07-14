"""Live routing check on three real external-apply URLs (recon 2026-07-14).

SAFETY: read-only. Navigates, scrapes, and classifies each page; it NEVER clicks
Submit, so no application is sent to Lemvos / DataDrive / SuperPlay. Opt-in and
excluded from the normal suite (pytest.ini addopts = -m "not live").

Run: make apply_probe
Flaky by nature (network, anti-bot, sites change). Replace URLs if they 404.
"""
import pytest

from app.application.classify_apply import classify
from app.domain.page_observation import Route
from app.infrastructure.channels.external_apply import scrape_form

pytestmark = pytest.mark.live

CASES = [
    ("https://join.com/companies/lemvos/16426802-mandatory-internship-web-development"
     "?pid=e65242534431eadcb0c9", Route.GATED, "click"),   # gate revealed after "Apply now"
    ("https://www.ddrive.tech/team/junior-software-developer", Route.EMAIL, "direct"),
    ("https://www.superplay.co/careers-position/26.D66/?coref=1.11.pF3_BB1B",
     Route.IFRAME_ATS, "direct"),
]


@pytest.fixture(scope="module")
def page():
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    pg = browser.new_context().new_page()
    yield pg
    browser.close()
    pw.stop()


@pytest.mark.parametrize("url,expected,mode", CASES, ids=lambda v: str(v)[:30])
def test_real_url_routes_as_expected(page, url, expected, mode):
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    if mode == "click":
        # join.com: the gate appears only after clicking "Apply now".
        btn = page.locator("button[data-testid='ApplyButton'], button:has-text('Apply now')")
        if btn.count():
            btn.first.click()
            page.wait_for_timeout(3000)
    obs = scrape_form(page)
    route = classify(obs)
    assert route is expected, f"{url} -> {route} (fields={len(obs.fields)}, iframes={obs.iframes[:1]})"
