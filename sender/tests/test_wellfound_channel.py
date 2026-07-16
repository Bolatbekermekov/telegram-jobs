import pytest

from app.domain.channel import (
    ChannelUnavailable,
    ManualApplyRequired,
    OutreachContent,
)
from app.infrastructure.channels.wellfound import WellfoundChannel, apply_via_page


# --- Fakes for apply_via_page --------------------------------------------------
#
# Modelled on the real Wellfound apply DOM (verified live 2026-07-17): clicking
# "Apply" opens a dialog whose message field is a <textarea> (often disabled) and
# whose submit control is a button "Send application" (disabled when the job is
# gated — e.g. not accepting applications from your location).

class _FakeLoc:
    def __init__(self, page, key, present=True, editable=True, enabled=True,
                 count=1, text=""):
        self._p, self._key = page, key
        self._present, self._editable, self._enabled = present, editable, enabled
        self._count, self._text = count, text

    @property
    def first(self):
        return self

    def nth(self, i):
        return self

    def count(self):
        return self._count

    def wait_for(self, state=None, timeout=None):
        if not self._present:
            raise TimeoutError(f"{self._key} not visible")

    def is_editable(self):
        return self._editable

    def is_enabled(self):
        return self._enabled

    def inner_text(self, timeout=None):
        return self._text

    def click(self):
        self._p.actions.append(("click", self._key))

    def fill(self, value, timeout=None):
        if not self._editable:
            raise TimeoutError("element is not enabled")
        self._p.actions.append(("fill", value))

    def locator(self, selector):
        if "textarea" in selector:
            return self._p._textarea_loc()
        return _FakeLoc(self._p, selector, present=False, count=0)


class _FakePage:
    def __init__(self, has_apply=True, note="editable", send_enabled=True,
                 dialog_text="YOUR APPLICATION",
                 title="Full Stack — Wellfound",
                 url="https://wellfound.com/jobs/123"):
        self.actions = []
        self._has_apply = has_apply
        self._note = note            # "editable" | "disabled" | None (absent)
        self._send_enabled = send_enabled
        self._dialog_text = dialog_text
        self._title, self._url = title, url

    def goto(self, url, **kw):
        self.actions.append(("goto", url))

    def wait_for_timeout(self, ms):
        pass   # no-op: the poll must not actually sleep in tests

    def title(self):
        return self._title

    @property
    def url(self):
        return self._url

    def _textarea_loc(self):
        if self._note is None:
            return _FakeLoc(self, "note", present=False, count=0)
        return _FakeLoc(self, "note", present=True,
                        editable=(self._note == "editable"), count=1)

    def get_by_role(self, role, name=None):
        if role == "dialog":
            return _FakeLoc(self, "dialog", text=self._dialog_text)
        if name == "Apply":
            return _FakeLoc(self, "Apply", present=self._has_apply)
        if name == "Send application":
            return _FakeLoc(self, "Send application", present=True,
                            enabled=self._send_enabled)
        return _FakeLoc(self, name)

    def locator(self, selector):
        if "textarea" in selector:
            return self._textarea_loc()
        return _FakeLoc(self, selector, present=False, count=0)


def test_apply_fills_message_and_submits_when_open():
    page = _FakePage(note="editable", send_enabled=True)
    apply_via_page(page, "https://wellfound.com/jobs/123", OutreachContent(body="Hi team"))
    assert ("goto", "https://wellfound.com/jobs/123") in page.actions
    assert ("click", "Apply") in page.actions
    assert ("fill", "Hi team") in page.actions
    assert ("click", "Send application") in page.actions


def test_apply_dry_run_fills_but_does_not_submit():
    page = _FakePage(note="editable", send_enabled=True)
    with pytest.raises(ManualApplyRequired) as exc:
        apply_via_page(page, "https://wellfound.com/jobs/9",
                       OutreachContent(body="Hi"), dry_run=True)
    assert "DRY_RUN" in str(exc.value)
    assert ("fill", "Hi") in page.actions
    assert ("click", "Send application") not in page.actions


def test_apply_manual_when_apply_button_never_renders():
    page = _FakePage(has_apply=False)
    with pytest.raises(ManualApplyRequired):
        apply_via_page(page, "https://wellfound.com/jobs/1", OutreachContent(body="Hi"))


def test_apply_manual_when_send_disabled_gated_by_location():
    # Real case: "Trace IP is not accepting applications from your current location".
    page = _FakePage(
        note="disabled", send_enabled=False,
        dialog_text=("YOUR APPLICATION Trace IP is not accepting applications from "
                     "your current location due to timezone or relocation constraints"))
    with pytest.raises(ManualApplyRequired) as exc:
        apply_via_page(page, "https://wellfound.com/jobs/4356164", OutreachContent(body="Hi"))
    assert "локац" in str(exc.value).lower()
    assert ("fill", "Hi") not in page.actions          # never blocked on the disabled field
    assert ("click", "Send application") not in page.actions   # nothing submitted


def test_apply_submits_one_click_job_with_no_message_field():
    page = _FakePage(note=None, send_enabled=True)
    apply_via_page(page, "https://wellfound.com/jobs/7", OutreachContent(body="Hi"))
    assert ("fill", "Hi") not in page.actions
    assert ("click", "Send application") in page.actions


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
    warm = _FakePage(note="editable", send_enabled=True)
    browser = _FakeBrowser(pages=[warm])
    pw = _FakePW(browser)
    _install_fake_pw(monkeypatch, pw)

    ch = WellfoundChannel("http://127.0.0.1:9222", dry_run=True)
    ch.start()
    with pytest.raises(ManualApplyRequired) as exc:
        ch.send("https://wellfound.com/jobs/123", OutreachContent(body="Hi"))
    assert "DRY_RUN" in str(exc.value)
    assert ("click", "Send application") not in warm.actions
