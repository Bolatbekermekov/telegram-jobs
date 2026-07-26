"""The DOM reader is thin, so these tests fake the page object — the same pattern
used by test_linkedin_channel.py and test_headhunter_channel.py."""
import pytest

from app.domain.contact import detect_contact
from app.domain.threads_post import post_body
from app.infrastructure.threads_thread import (
    author_from_url, read_thread_blocks, render_thread, resolve_thread,
)

_URL = "https://www.threads.com/@lnkrnchk/post/DbL4LxBl6v9"

_BLOCKS = [
    ["@lnkrnchk", ["hiring", "1 дн.", "Ищу Full Stack Developer.", "32"]],
    ["@lnkrnchk", ["hiring", "1 дн.", "·", "Автор", "Что важно: опыт с Lovable.", "1"]],
    ["@lnkrnchk", ["hiring", "1 дн.", "·", "Автор",
                   "Для отклика присылайте портфолио в Telegram: @ skyluckwalker", "1"]],
    ["@troll", ["1 дн.", "Навайбкодили нейрослоп.", "3"]],
]


class FakePage:
    """Mimics the bits of a Playwright page that the reader touches."""

    def __init__(self, blocks=None, goto_error=None, eval_error=None):
        self._blocks = blocks if blocks is not None else _BLOCKS
        self._goto_error = goto_error
        self._eval_error = eval_error
        self.goto_calls = []

    def goto(self, url, **kwargs):
        self.goto_calls.append(url)
        if self._goto_error:
            raise self._goto_error

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, script):
        if self._eval_error:
            raise self._eval_error
        return self._blocks


def test_author_from_url():
    assert author_from_url(_URL) == "@lnkrnchk"
    assert author_from_url("https://www.threads.net/@a.b/post/X1") == "@a.b"
    assert author_from_url("https://hh.ru/vacancy/1") == ""
    assert author_from_url("") == ""


def test_read_thread_blocks_normalises_to_tuples():
    blocks = read_thread_blocks(FakePage())
    assert blocks[0] == ("@lnkrnchk", ["hiring", "1 дн.", "Ищу Full Stack Developer.", "32"])
    assert len(blocks) == 4


def test_read_thread_blocks_tolerates_junk_rows():
    page = FakePage(blocks=[["@a", ["text long enough"]], None, ["@b"], "nonsense",
                            ["@c", "not-a-list"]])
    assert read_thread_blocks(page) == [("@a", ["text long enough"])]


def test_resolve_thread_returns_only_the_authors_posts():
    text = resolve_thread(FakePage(), _URL)
    assert "Ищу Full Stack Developer." in text
    assert "Что важно: опыт с Lovable." in text
    assert "@ skyluckwalker" in text
    assert "Навайбкодили" not in text


def test_resolve_thread_keeps_thread_order():
    text = resolve_thread(FakePage(), _URL)
    assert text.index("Ищу Full Stack") < text.index("Что важно") < text.index("Для отклика")


def test_resolve_thread_navigates_to_the_url():
    page = FakePage()
    resolve_thread(page, _URL)
    assert page.goto_calls == [_URL]


def test_resolve_thread_returns_empty_when_navigation_fails():
    """A login wall, a timeout or a network blip must not raise: the caller falls
    back to the 480 chars the intake already stored."""
    assert resolve_thread(FakePage(goto_error=RuntimeError("timeout")), _URL) == ""


def test_resolve_thread_returns_empty_when_the_dom_read_fails():
    assert resolve_thread(FakePage(eval_error=RuntimeError("detached")), _URL) == ""


def test_resolve_thread_returns_empty_when_the_page_has_no_posts():
    assert resolve_thread(FakePage(blocks=[]), _URL) == ""


def test_resolve_thread_returns_empty_for_a_non_threads_url():
    assert resolve_thread(FakePage(), "https://hh.ru/vacancy/1") == ""


def test_resolve_thread_does_not_open_a_page_for_a_non_threads_url():
    """The URL check comes first: a non-Threads lead must not cost a page load."""
    page = FakePage()
    resolve_thread(page, "https://hh.ru/vacancy/1")
    assert page.goto_calls == []


def test_render_thread_rejects_a_non_threads_url_without_launching_a_browser():
    """The send loop calls this per lead, so the URL is checked before Playwright
    is even imported — which is also what keeps this test offline."""
    assert render_thread("https://hh.ru/vacancy/1") == ""
    assert render_thread("") == ""


# --- the contact, which is the whole point of reading the thread ----------------
#
# Measured live 2026-07-26 (see task-6-report.md). Threads renders a real mention
# as `a[href^="/@"]` wrapped in block-level <div>s, so plain innerText returns
# "…Telegram: \n@nick\n" and breaks the sentence. The reader unwraps that anchor,
# so the handle reaches this text glued to its own at-sign.

def test_detect_contact_finds_a_glued_mention_in_the_assembled_thread_text():
    page = FakePage(blocks=[
        ["@lnkrnchk", ["hiring", "1 дн.", "Ищу Full Stack Developer.", "32"]],
        ["@lnkrnchk", ["hiring", "1 дн.", "·", "Автор",
                       "Для отклика присылайте портфолио в Telegram: @skyluckwalker", "1"]],
    ])
    contact = detect_contact(resolve_thread(page, _URL))
    assert contact is not None
    assert contact.platform == "telegram"
    assert contact.target == "@skyluckwalker"


def test_an_at_sign_the_author_typed_with_a_space_stays_undetectable():
    """Documents an OPEN decision, not a desired outcome.

    On the live post the author typed «в Telegram: @ skyluckwalker» — with the
    space — and Threads stored it that way (its own payload carries
    "Telegram: \\u0040 skyluckwalker" with linkified_in_app_url: null, because the
    space stops it being a mention). So this is not a rendering artifact the DOM
    reader can undo: the DOM reproduces the author's text faithfully.

    Closing it needs a text-level rule, and the obvious one — a blanket
    `@\\s+` -> `@` — is the change that was reverted from detect_contact, because
    it turns "hr @ acme.com" into "@acme" and "Role @ Astana" into "@Astana".
    Left undetected on purpose pending a human decision; see task-6-report.md.
    """
    text = resolve_thread(FakePage(), _URL)
    assert "@ skyluckwalker" in text
    assert detect_contact(text) is None


# --- the block finder, against a real DOM ---------------------------------------
#
# FakePage cannot reach this: its evaluate() hands back canned blocks, so it stops
# at the Python normaliser and never runs the JS. Finding the post block IS the JS,
# so covering it needs a real DOM — built from a string, never fetched. set_content
# issues no network request, so these stay in the offline suite; they do need the
# chromium binary, which the sender needs anyway to send anything at all.


@pytest.fixture(scope="module")
def dom_blocks():
    """read_thread_blocks() over markup served from memory."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f"playwright is not installed: {exc}")
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch(headless=True)
    except Exception as exc:  # pragma: no cover — no browser binary on this box
        pw.stop()
        pytest.skip(f"chromium is not installed (playwright install chromium): {exc}")
    page = browser.new_context().new_page()
    try:
        def read(html):
            page.set_content(html)
            return read_thread_blocks(page)
        yield read
    finally:
        browser.close()
        pw.stop()


def _card(handle, post_id, body, tag="hiring"):
    """One post card in the shape measured on the live page 2026-07-26.

    What matters for the finder: the [data-pressable-container] that marks the card,
    an avatar link carrying no text three levels below it, a header row holding the
    name link and the timestamp permalink, and the body span. The nesting depth is
    the measured one, so the climb the old reader did is reproduced exactly: from the
    avatar link the post's own text first appears at hop 3 and then PLATEAUS, and the
    thread wrapper stays out of reach of the six hops it was allowed.
    """
    return f"""
    <div><div><div data-pressable-container="true" data-interactive-id="">
      <div><div>
        <div><div><a href="/{handle}" role="link"><img alt=""></a></div></div>
        <div>
          <div><a href="/{handle}" role="link"><div><span><span
             >{handle[1:]}</span></span></div></a></div>
          <span dir="auto">{tag}</span>
          <a href="/{handle}/post/{post_id}" role="link"><span><div><span
             dir="auto">1d</span></div></span></a>
        </div>
        <div><span dir="auto">{body}</span></div>
      </div></div>
    </div></div></div>"""


_LONG = "Ищу Full Stack Developer (Lovable / Claude Code / AI-first)."
_SHORT = "тг: @acme_hr"          # 12 chars — the shape a terse contact reply takes

_THREAD_HTML = f"""<div id="thread"><div><div>
  <span dir="auto">Ветка</span>
  {_card("@lnkrnchk", "DbL4LxBl6v9", _LONG)}
  {_card("@lnkrnchk", "DbL4Lvgl74r", _SHORT)}
</div></div></div>"""


def test_the_block_finder_finds_a_self_reply_too_short_to_pass_a_length_threshold(
        dom_blocks):
    """The whole point of reading the thread is the contact, and the contact is
    routinely a one-line self-reply. The old finder climbed to the first ancestor
    running past 40 characters, so a reply this short was never found at all and the
    post vanished with no signal — post_body cannot recover what is never emitted.
    """
    blocks = dom_blocks(_THREAD_HTML)
    assert [h for h, _ in blocks] == ["@lnkrnchk", "@lnkrnchk"]
    assert post_body(blocks[0][1]) == _LONG
    assert post_body(blocks[1][1]) == _SHORT


def test_the_block_finder_does_not_emit_the_thread_wrapper(dom_blocks):
    """The wrapper holds every post, so emitting it would duplicate the whole thread
    under whichever handle happened to be found first."""
    for _, parts in dom_blocks(_THREAD_HTML):
        assert "Ветка" not in parts


# the quoted card measured 187 chars live, well past any length threshold
_QUOTED = "Excited about this launch, the team moved remarkably fast on it."

_QUOTE_HTML = f"""<div id="thread"><div><div>
  <div><div><div data-pressable-container="true">
    <div><div>
      <div><div><a href="/@lnkrnchk" role="link"><img alt=""></a></div></div>
      <div><div><a href="/@lnkrnchk" role="link"><div><span><span
         >lnkrnchk</span></span></div></a></div></div>
      <div><span dir="auto">{_LONG}</span></div>
      {_card("@zuck", "DbQuoted01", _QUOTED, tag="")}
    </div></div>
  </div></div></div>
</div></div></div>"""


def test_a_quoted_card_does_not_replace_the_post_that_quotes_it(dom_blocks):
    """Quote posts nest one card inside another. Keeping the INNER one drops the
    author's own text — measured live on @mosseri's feed, where it returned «@zuck»
    with an empty body and lost «Excited about this launch…» entirely.
    """
    blocks = dom_blocks(_QUOTE_HTML)
    assert [h for h, _ in blocks] == ["@lnkrnchk"]
    assert _LONG in post_body(blocks[0][1])


# --- selector drift canary -----------------------------------------------------
#
# Meta ships DOM changes without notice, so the JS is pinned against the real page.
# Deselected by `make test-unit`; run with `sender/.venv/bin/python -m pytest
# sender/tests/test_threads_thread.py -m live`.

@pytest.mark.live
def test_live_render_thread_reads_the_whole_authors_thread():
    text = render_thread(_URL)
    # the root post and BOTH self-replies, none of which og:description carries
    assert "Ищу Full Stack Developer" in text
    assert "Что важно:" in text
    assert "Для отклика присылайте портфолио в Telegram:" in text
    # foreign replies stay out: trolling and other candidates' CVs
    assert "Навайбкодили" not in text
    assert "резюме" not in text
    # the bullet lists keep the line breaks that separate their items
    assert "\n— развивать существующий продукт;" in text


@pytest.mark.live
def test_live_render_thread_emits_no_interface_chrome():
    text = render_thread(_URL)
    # the in-body translate control, which sits INSIDE the body span and so used
    # to arrive glued to the last line of the vacancy
    assert "Translate" not in text
    assert "Показать перевод" not in text
    # engagement counters, including the abbreviated forms that shape cannot catch
    for junk in ("тыс.", "views", "просмотр"):
        assert junk not in text
    # the author handle span, which would shield the badge row into the body
    assert "lnkrnchk" not in text
    assert "Автор" not in text and "Author" not in text


@pytest.mark.live
def test_live_render_thread_returns_empty_for_a_dead_post():
    """A deleted or private post must degrade to "", not raise."""
    assert render_thread("https://www.threads.com/@lnkrnchk/post/ZZZZnotapost") == ""
