"""Pressing «Отправить» in LinkedIn's message overlay.

Lead #160 (2026-07-30) died on `Locator.click: Timeout 30000ms exceeded` against
`button.msg-form__send-button`, looping «element is visible, enabled and stable /
scrolling into view if needed / done scrolling / element is outside of the
viewport» for the full 30s. Measured live on the same profile at the run's own
1280x720 viewport:

* the composer lives in `div.application-outlet__overlay-container`, which is
  `position: fixed`, on a page where `scrollHeight == innerHeight` — there is
  nothing to scroll, so "scroll it into view" can never change the answer;
* an open conversation bubble sits at y=100..720 and its send button at y=682 —
  fine. A MINIMISED one keeps its full 620px height and slides 572px down, so the
  same button sits at **y=1254** in a 720px viewport: visible, enabled, stable,
  and permanently out of reach of a hit-point click.

So the send must go through a native el.click() like every other control in this
file — and, because a native click on a disabled button is a silent no-op, it must
be confirmed rather than assumed. The button stays disabled until the CV upload
finishes (verified live: empty box -> is_enabled() False, filled -> True), which
is the wait Playwright's own .click() used to do for us.
"""
import pytest

from app.domain.channel import ChannelError, OutreachContent
from app.infrastructure.channels.linkedin import (
    SEL_FILE_INPUT,
    SEL_MESSAGE_BTN,
    SEL_MSG_BOX,
    SEL_MSG_SEND,
    fill_and_send,
)


class _FakeComposer:
    """A message overlay whose send button behaves like the real one: disabled
    while the box is empty, and a click empties the box (that is what "sent"
    looks like — verified live, inner_text() goes back to '\\n')."""

    def __init__(self, *, forms=1, enable_after=0, dead_button=False):
        self.actions = []
        self.text = ""
        self._forms = forms
        self._enable_after = enable_after     # polls to survive before enabling
        self._dead = dead_button              # click lands but nothing is sent
        self.keyboard = _FakeKeyboard(self)

    def goto(self, url, **kw):
        self.actions.append(("goto", url))

    def wait_for_timeout(self, ms):
        pass

    def wait_for_load_state(self, state=None, timeout=None):
        pass

    def _count(self, selector):
        if selector in (SEL_MSG_BOX, SEL_MSG_SEND):
            return self._forms
        if selector == SEL_MESSAGE_BTN:
            return 1
        if selector == SEL_FILE_INPUT:
            return 1
        return 0

    def locator(self, selector):
        page = self

        class _Loc:
            def __init__(self_inner, which="all"):
                self_inner.which = which

            def count(self_inner):
                return page._count(selector)

            @property
            def first(self_inner):
                return _Loc("first")

            @property
            def last(self_inner):
                return _Loc("last")

            def click(self_inner, timeout=None):
                page.actions.append(("click", selector, self_inner.which))

            def focus(self_inner):
                page.actions.append(("focus", selector, self_inner.which))

            def fill(self_inner, value):
                page.actions.append(("fill", selector, self_inner.which, value))
                if selector == SEL_MSG_BOX:
                    page.text = value

            def set_input_files(self_inner, path):
                page.actions.append(("set_input_files", selector, path))

            def is_enabled(self_inner):
                if selector != SEL_MSG_SEND:
                    return True
                if page._enable_after > 0:
                    page._enable_after -= 1
                    return False
                return bool(page.text)

            def inner_text(self_inner, timeout=None):
                # The live composer answers '\n' when empty, never ''.
                return page.text if page.text else "\n"

            def evaluate(self_inner, expr, timeout=None):
                page.actions.append(("jsclick", selector, self_inner.which))
                if selector == SEL_MSG_SEND and not page._dead:
                    page.text = ""            # the message left the composer

        return _Loc()


class _FakeKeyboard:
    def __init__(self, page):
        self._page = page

    def press(self, key):
        self._page.actions.append(("press", key))
        if key == "Enter":
            self._page.text = ""


def _send(page, body="Здравствуйте!"):
    fill_and_send(page, "https://linkedin.com/in/someone", OutreachContent(body=body))


def test_send_uses_a_native_click_not_a_hit_point_click():
    """A hit-point click needs the button inside the viewport; a minimised bubble
    parks it 534px below the fold on a page that cannot scroll."""
    page = _FakeComposer()
    _send(page)

    assert any(a[:2] == ("jsclick", SEL_MSG_SEND) for a in page.actions)
    assert not any(a[:2] == ("click", SEL_MSG_SEND) for a in page.actions)


def test_the_box_is_focused_rather_than_hit_point_clicked():
    """Same hazard, one line up: measured live on a minimised bubble, click() on
    the box times out while focus()/fill() work — neither needs a hit point."""
    page = _FakeComposer()
    _send(page)

    assert any(a[:2] == ("focus", SEL_MSG_BOX) for a in page.actions)
    assert not any(a[:2] == ("click", SEL_MSG_BOX) for a in page.actions)


def test_send_targets_the_same_composer_the_text_went_into():
    """The box is filled through `.last` and the button was pressed through
    `.first` — different forms the moment LinkedIn docks more than one bubble."""
    page = _FakeComposer(forms=2)
    _send(page)

    fill_end = next(a[2] for a in page.actions if a[0] == "fill" and a[1] == SEL_MSG_BOX)
    send_end = next(a[2] for a in page.actions if a[0] == "jsclick" and a[1] == SEL_MSG_SEND)
    assert send_end == fill_end


def test_send_waits_for_the_button_to_enable():
    """LinkedIn keeps «Отправить» disabled until the CV upload lands, and a native
    click on a disabled button is a silent no-op — so the wait Playwright's own
    click gave us has to be kept."""
    page = _FakeComposer(enable_after=3)
    _send(page)

    assert any(a[:2] == ("jsclick", SEL_MSG_SEND) for a in page.actions)
    assert page.text == ""


def test_send_raises_when_the_button_never_enables():
    page = _FakeComposer(enable_after=10**6)
    with pytest.raises(ChannelError, match="Отправить"):
        _send(page)
    assert not any(a[:2] == ("jsclick", SEL_MSG_SEND) for a in page.actions)


def test_send_raises_when_the_text_stays_in_the_composer():
    """The one thing worse than a failed send is a silent one: the lead would be
    written down as `sent` with nothing delivered."""
    page = _FakeComposer(dead_button=True)
    with pytest.raises(ChannelError, match="не подтверждена"):
        _send(page)


def test_enter_fallback_is_still_confirmed():
    """No send button at all — the Enter fallback answers for itself too."""
    page = _FakeComposer(forms=0)
    page._count = lambda sel: 1 if sel in (SEL_MESSAGE_BTN, SEL_MSG_BOX) else 0
    _send(page)
    assert ("press", "Enter") in page.actions
