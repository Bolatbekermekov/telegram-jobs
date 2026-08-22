"""The send control is read from the SAME bubble as the box that was filled.

Both facts here are measured, not imagined — live on 2026-08-22, on a profile
with a docked conversation already open in the same tab:

* an EXISTING thread's composer carries `button.msg-form__send-button`;
* a NEW message opened from a profile carries `button.msg-form__send-btn`
  instead (artdeco-button--circle, type=submit, icon `send-privately-small`),
  and no `send-button` anywhere inside it.

The profile path always opens the second kind. On the sender's own fresh context
— no docked chat, so no `send-button` on the page at all — the old selector
matched nothing, `_press_send` fell through to Enter, and that form does not send
on Enter: it has a subject field above the body. The lead failed as «текст остался
в поле ввода», which was the honest answer to a send that never happened.

With a docked chat present the same code found exactly one `send-button` — the
DOCKED one — while the filled box was the profile overlay's. That is the shape
these tests exist to make impossible: two `.last` calls over two independent
lists can name two different conversations.
"""
import pytest

from app.domain.channel import ChannelError, OutreachContent
from app.infrastructure.channels.linkedin import (
    SEL_FILE_INPUT,
    SEL_MESSAGE_BTN,
    SEL_MSG_BOX,
    SEL_MSG_BUBBLE,
    SEL_MSG_SEND,
    fill_and_send,
)


class _Bubble:
    """One conversation overlay: its own box, its own send button."""

    # The class the live bubble actually renders. A docked thread and a fresh
    # profile overlay do not share it, and that difference is the whole bug —
    # so the fake answers on the CLASS, never on "some send exists".
    OLD_THREAD = "msg-form__send-button"
    NEW_COMPOSE = "msg-form__send-btn"

    def __init__(self, name, *, send_class=NEW_COMPOSE):
        self.name = name
        self.text = ""
        self.send_class = send_class
        self.pressed = False


class _FakePage:
    """A page holding several bubbles, the way LinkedIn stacks them.

    `bubbles[-1]` is the one just opened — that is the order the live DOM had:
    the docked chat first, the profile's new-message overlay appended after it.
    """

    def __init__(self, bubbles, *, bubble_class=True):
        self.bubbles = bubbles
        self._bubble_class = bubble_class   # False = a layout with no bubble node
        self.keyboard = _FakeKeyboard(self)
        self.enter_presses = 0

    def goto(self, url, **kw):
        pass

    def wait_for_timeout(self, ms):
        pass

    def wait_for_load_state(self, state=None, timeout=None):
        pass

    def locator(self, selector):
        if selector == SEL_MSG_BUBBLE:
            return _BubbleList(self.bubbles if self._bubble_class else [])
        if selector == SEL_MESSAGE_BTN:
            return _Simple(1)
        # Unscoped box/send: what the page would answer if nothing narrowed it
        # down. Deliberately WRONG on purpose — the first bubble, not the last —
        # so a test fails loudly if the code ever reads these from the page again.
        if selector in (SEL_MSG_BOX, SEL_MSG_SEND, SEL_FILE_INPUT):
            return _InBubble(self.bubbles[0], selector)
        return _Simple(0)


class _BubbleList:
    def __init__(self, bubbles):
        self._bubbles = bubbles

    def count(self):
        return len(self._bubbles)

    @property
    def last(self):
        return _BubbleScope(self._bubbles[-1])

    @property
    def first(self):
        return _BubbleScope(self._bubbles[0])


class _BubbleScope:
    """What `page.locator(SEL_MSG_BUBBLE).last` hands back: a scope whose
    `.locator()` can only ever see inside this one bubble."""

    def __init__(self, bubble):
        self.bubble = bubble

    def locator(self, selector):
        return _InBubble(self.bubble, selector)


class _InBubble:
    def __init__(self, bubble, selector):
        self.bubble = bubble
        self.selector = selector

    def count(self):
        if self.selector == SEL_MSG_SEND:
            # Matches only if the selector names the class THIS bubble renders.
            cls = self.bubble.send_class
            return 1 if cls and cls in self.selector else 0
        return 1

    @property
    def first(self):
        return self

    @property
    def last(self):
        return self

    def focus(self):
        pass

    def click(self, timeout=None):
        pass

    def fill(self, value):
        self.bubble.text = value

    def set_input_files(self, path):
        pass

    def is_enabled(self):
        # The live button enables once its OWN box has text — which is exactly
        # why a send read from the wrong bubble never enables.
        return bool(self.bubble.text)

    def inner_text(self, timeout=None):
        return self.bubble.text or "\n"

    def evaluate(self, expr, timeout=None):
        self.bubble.pressed = True
        self.bubble.text = ""      # a real send empties the composer


class _Simple:
    def __init__(self, count):
        self._count = count

    def count(self):
        return self._count

    @property
    def first(self):
        return self

    @property
    def last(self):
        return self

    def click(self, timeout=None):
        pass

    def evaluate(self, expr, timeout=None):
        pass


class _FakeKeyboard:
    def __init__(self, page):
        self._page = page

    def press(self, key):
        if key == "Enter":
            self._page.enter_presses += 1
            # The new-message form does NOT send on Enter — it has a subject
            # field, and Enter puts a newline in the body. So: nothing clears.


def _send(page):
    fill_and_send(page, "https://www.linkedin.com/in/someone",
                  OutreachContent(body="Здравствуйте!"))


def test_the_send_is_pressed_in_the_bubble_that_was_filled():
    docked = _Bubble("Jeevan Kumar", send_class=_Bubble.OLD_THREAD)
    profile = _Bubble("Valiaryan Kazhaneuski")  # the one this run opened
    page = _FakePage([docked, profile])

    _send(page)

    assert profile.pressed, "нажали не в том пузыре"
    assert not docked.pressed, "нажали Send в чужой переписке"
    assert docked.text == "", "письмо ушло в чужой композер"


def test_a_form_whose_only_send_is_the_new_class_still_sends():
    """The live profile overlay: `send-btn` present, `send-button` absent."""
    profile = _Bubble("Valiaryan Kazhaneuski")
    page = _FakePage([profile])

    _send(page)

    assert profile.pressed
    assert page.enter_presses == 0, "Enter — это фолбэк, а не способ отправки"


def test_a_send_that_never_happened_is_never_reported_as_sent():
    """No send control at all -> Enter -> this form ignores it -> the text stays.
    The failure must survive: a lead recorded as sent with nothing sent is the
    one outcome worse than a failed one."""
    profile = _Bubble("Valiaryan Kazhaneuski", send_class=None)
    page = _FakePage([profile])

    with pytest.raises(ChannelError, match="текст остался в поле ввода"):
        _send(page)

    assert page.enter_presses == 1


def test_a_layout_with_no_bubble_node_still_works():
    """The fallback: nothing matches SEL_MSG_BUBBLE, so the page answers. Kept
    because a selector that stops matching must degrade to the old behaviour
    rather than crash the run."""
    only = _Bubble("единственный")
    page = _FakePage([only], bubble_class=False)

    _send(page)

    assert only.pressed
