import pytest

from app.domain.channel import (
    ChannelUnavailable,
    ManualApplyRequired,
    OutreachContent,
)
from app.infrastructure.channels.wellfound import WellfoundChannel, apply_via_page


# --- Fakes for apply_via_page (a Playwright page, driven by locators) ----------

class _FakeLocator:
    """A Playwright-locator stand-in. `present=False` makes wait_for() time out,
    simulating an element that never rendered."""

    def __init__(self, page, key, present):
        self._page, self._key, self._present = page, key, present

    @property
    def first(self):
        return self

    def wait_for(self, state=None, timeout=None):
        if not self._present:
            raise TimeoutError(f"{self._key} not visible")

    def click(self):
        self._page.actions.append(("click", self._key))

    def fill(self, value):
        self._page.actions.append(("fill", value))


class _FakePage:
    def __init__(self, has_apply=True, has_note=True,
                 title="Full Stack — Wellfound",
                 url="https://wellfound.com/jobs/123"):
        self.actions = []
        self._has_apply = has_apply
        self._has_note = has_note
        self._title = title
        self._url = url

    def goto(self, url, **kw):
        self.actions.append(("goto", url))

    def title(self):
        return self._title

    @property
    def url(self):
        return self._url

    def get_by_role(self, role, name=None):
        present = self._has_apply if name == "Apply" else True
        return _FakeLocator(self, name, present)

    def get_by_placeholder(self, text):
        return _FakeLocator(self, "note", self._has_note)


def test_apply_fills_message_and_submits():
    page = _FakePage(has_apply=True, has_note=True)
    apply_via_page(page, "https://wellfound.com/jobs/123", OutreachContent(body="Hi team"))
    assert ("goto", "https://wellfound.com/jobs/123") in page.actions
    assert ("click", "Apply") in page.actions
    assert ("fill", "Hi team") in page.actions
    assert ("click", "Submit application") in page.actions


def test_apply_dry_run_fills_but_does_not_submit():
    page = _FakePage(has_apply=True, has_note=True)
    with pytest.raises(ManualApplyRequired) as exc:
        apply_via_page(page, "https://wellfound.com/jobs/9",
                       OutreachContent(body="Hi"), dry_run=True)
    assert "DRY_RUN" in str(exc.value)
    assert ("fill", "Hi") in page.actions
    assert ("click", "Submit application") not in page.actions


def test_apply_manual_when_apply_button_never_renders():
    page = _FakePage(has_apply=False)
    with pytest.raises(ManualApplyRequired):
        apply_via_page(page, "https://wellfound.com/jobs/1", OutreachContent(body="Hi"))


def test_apply_survives_missing_note_box():
    # Some Wellfound applications have no message box — that must not abort the apply.
    page = _FakePage(has_apply=True, has_note=False)
    apply_via_page(page, "https://wellfound.com/jobs/2", OutreachContent(body="Hi"))
    assert ("click", "Apply") in page.actions
    assert ("fill", "Hi") not in page.actions
    assert ("click", "Submit application") in page.actions


# --- Fakes for the CDP attach (start/stop) ------------------------------------

class _FakeCtx:
    def __init__(self, pages):
        self.pages = pages
        self.new_page_calls = 0

    def new_page(self):
        self.new_page_calls += 1
        p = _FakePage()
        self.pages = [p]
        return p


class _FakeBrowser:
    def __init__(self, pages):
        self.contexts = [_FakeCtx(pages)]
        self.closed = False

    def close(self):
        self.closed = True


class _FakeChromium:
    def __init__(self, browser, fail=False):
        self._browser = browser
        self._fail = fail
        self.connected = []

    def connect_over_cdp(self, url):
        self.connected.append(url)
        if self._fail:
            raise RuntimeError("ECONNREFUSED 127.0.0.1:9222")
        return self._browser


class _FakePW:
    def __init__(self, browser, fail=False):
        self.chromium = _FakeChromium(browser, fail)
        self.stopped = False

    def stop(self):
        self.stopped = True


def _install_fake_pw(monkeypatch, pw):
    import patchright.sync_api as psa

    class _Factory:
        def start(self_inner):
            return pw

    monkeypatch.setattr(psa, "sync_playwright", lambda: _Factory())


def test_start_attaches_over_cdp_and_reuses_warm_page(monkeypatch):
    warm = _FakePage()
    browser = _FakeBrowser(pages=[warm])
    pw = _FakePW(browser)
    _install_fake_pw(monkeypatch, pw)

    ch = WellfoundChannel("http://127.0.0.1:9222")
    ch.start()

    assert pw.chromium.connected == ["http://127.0.0.1:9222"]  # attached, not launched
    assert ch._page is warm                                    # reused the warm tab
    assert browser.closed is False


def test_start_raises_channel_unavailable_when_chrome_down(monkeypatch):
    pw = _FakePW(browser=None, fail=True)
    _install_fake_pw(monkeypatch, pw)

    ch = WellfoundChannel("http://127.0.0.1:9222")
    with pytest.raises(ChannelUnavailable):
        ch.start()
    assert pw.stopped is True   # driver cleaned up, not leaked


def test_stop_leaves_the_users_chrome_running(monkeypatch):
    warm = _FakePage()
    browser = _FakeBrowser(pages=[warm])
    pw = _FakePW(browser)
    _install_fake_pw(monkeypatch, pw)

    ch = WellfoundChannel("http://127.0.0.1:9222")
    ch.start()
    ch.stop()

    assert browser.closed is False   # never close the CDP-attached Chrome
    assert pw.stopped is True


def test_send_honours_dry_run_flag(monkeypatch):
    warm = _FakePage(has_apply=True, has_note=True)
    browser = _FakeBrowser(pages=[warm])
    pw = _FakePW(browser)
    _install_fake_pw(monkeypatch, pw)

    ch = WellfoundChannel("http://127.0.0.1:9222", dry_run=True)
    ch.start()
    with pytest.raises(ManualApplyRequired) as exc:
        ch.send("https://wellfound.com/jobs/123", OutreachContent(body="Hi"))
    assert "DRY_RUN" in str(exc.value)
    assert ("click", "Submit application") not in warm.actions
