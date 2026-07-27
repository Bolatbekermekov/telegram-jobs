"""The DOM reader is thin, so these tests fake the page object — the same pattern
used by test_linkedin_channel.py and test_headhunter_channel.py."""
import pytest

from app.domain.contact import detect_contact
from app.domain.threads_post import post_body
from app.infrastructure.threads_thread import (
    _COUNT_JS, _SCROLL_ROUNDS, _SETTLE_MS, author_from_url, load_whole_thread,
    read_thread_blocks, render_thread, resolve_thread,
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
        self.evaluated = []

    def goto(self, url, **kwargs):
        self.goto_calls.append(url)
        if self._goto_error:
            raise self._goto_error

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, script):
        if self._eval_error:
            raise self._eval_error
        # Script-aware, because the reader now runs three different scripts and a
        # page that answered all of them with the block list would not be a fake of
        # anything: `load_whole_thread` compares the count to an int.
        self.evaluated.append(script)
        if "scrollTop" in script:
            return None
        if ".length" in script:
            return len(self._blocks)
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


# --- the thread is paginated, so it has to be scrolled --------------------------
#
# goto + settle alone renders the top of the thread only, and the author's own
# self-replies — the entire reason this module exists — sit BELOW the root post.
# Measured live 2026-07-27 (see the comment on _SCROLL_JS): 14 -> 22 containers on a
# 281-reply thread, 8 -> 13 on the canary thread, while waiting 32 s without
# scrolling moved neither.

class _GrowingPage:
    """A page that reveals more posts on every scroll — Threads' own pagination.

    `counts=None` means a feed that never stops growing, which is what the round
    bound exists for.
    """

    def __init__(self, counts=None):
        self._counts = counts
        self.scrolls = 0

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, script):
        if "scrollTop" in script:
            self.scrolls += 1
            return None
        if self._counts is None:
            return self.scrolls * 10
        return self._counts[min(self.scrolls, len(self._counts) - 1)]


def test_load_whole_thread_scrolls_until_the_count_stops_growing():
    """Two rounds is the normal cost: one that loads the rest, one that proves
    nothing more is coming."""
    page = _GrowingPage([8, 13, 13, 13])
    assert load_whole_thread(page) == 13
    assert page.scrolls == 2


def test_load_whole_thread_is_bounded_when_the_feed_never_ends():
    """The page is not ours. An infinite feed must cost a fixed number of rounds,
    not hang the send loop, which pays this per lead."""
    page = _GrowingPage()
    load_whole_thread(page)
    assert page.scrolls == _SCROLL_ROUNDS


def test_load_whole_thread_stops_instead_of_raising_on_an_uncountable_page():
    """A non-int count must END the loop, never raise: resolve_thread's except
    would turn it into "", i.e. a lead with no vacancy text at all, which is a far
    worse outcome than one unscrolled thread."""
    page = FakePage()
    page.evaluate = lambda script: "not a number"
    assert load_whole_thread(page) == 0


def _page_whose_scroll_raises(exc=None):
    """A page that reads fine and cannot be scrolled — the live shape of an SPA
    navigating under us (a login interstitial reached mid-scroll), which Playwright
    reports as "Execution context was destroyed"."""
    page = FakePage()
    inner = page.evaluate

    def evaluate(script):
        if "scrollTop" in script:
            raise exc or RuntimeError("Execution context was destroyed")
        return inner(script)

    page.evaluate = evaluate
    return page


def test_load_whole_thread_stops_instead_of_raising_when_the_scroll_itself_raises():
    """The count's TYPE was guarded and the evaluate CALL was not, which is the
    likelier raise of the two by far."""
    assert load_whole_thread(_page_whose_scroll_raises()) == 0


def test_a_scroll_that_raises_still_returns_what_the_page_already_showed():
    """Degrade to "read what we have", never to "read nothing". Unguarded, the raise
    reaches resolve_thread's except and becomes "" — a lead with NO vacancy text and
    no contact, off a page that reads perfectly well."""
    text = resolve_thread(_page_whose_scroll_raises(), _URL)
    assert "Ищу Full Stack Developer." in text
    assert "Что важно: опыт с Lovable." in text
    assert "Навайбкодили нейрослоп." not in text     # still only the author's posts


def test_resolve_thread_scrolls_before_it_reads():
    """Order is load-bearing: reading first would capture only the top of the
    thread and the scroll would be wasted."""
    page = FakePage()
    resolve_thread(page, _URL)
    assert any("scrollTop" in s for s in page.evaluated)
    scrolled = next(i for i, s in enumerate(page.evaluated) if "scrollTop" in s)
    read = next(i for i, s in enumerate(page.evaluated)
                if "data-pressable-container" in s and "scrollTop" not in s
                and ".length" not in s)
    assert scrolled < read


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


# The quoted card measured 187 chars live, well past any length threshold. It carries
# a handle on purpose: a quoted post is written by SOMEONE ELSE, so any contact in it
# belongs to a stranger.
_STRANGER = "@stranger_hr"
_QUOTED = f"Мы тоже нанимаем, пишите мне {_STRANGER} прямо сейчас."

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


def test_a_quoted_cards_text_is_not_collected_as_the_authors_own(dom_blocks):
    """Attributing the block to the author is only half of it: the span query runs
    over the whole outer card, so without scoping it also sweeps up the nested card's
    body. The handle-based defence in author_thread_text cannot catch that — the block
    IS the author's. A stranger's «пишите мне @stranger_hr» would then read as the
    vacancy's own contact and the outreach would go to them.

    It also defeats the guard Task 8 plans, which checks a model-proposed contact
    against the source text: here the stranger's handle really is in the source text.
    """
    body = post_body(dom_blocks(_QUOTE_HTML)[0][1])
    assert _QUOTED not in body
    assert _STRANGER not in body
    assert detect_contact(body) is None


# The markup a real linkified mention arrives in, measured live 2026-07-26: Threads
# wraps the anchor in block-level <div>s, so plain innerText tears the handle onto a
# line of its own and orphans the punctuation after it. The reader unwraps the anchor
# before reading; this is the only thing pinning that.
_MENTION = ('<span>Пишите </span>'
            '<div><span><div><a href="/@acme_hr" role="link">'
            '<span translate="no">@acme_hr</span></a></div></span></div>'
            '<span>, это наш HR.</span>')

_MENTION_HTML = f"""<div id="thread"><div><div>
  {_card("@lnkrnchk", "DbMention01", _MENTION)}
</div></div></div>"""


def test_a_linkified_mention_comes_back_glued_into_its_sentence(dom_blocks):
    """Unwrapping the anchor is what makes the contact readable at all: torn apart,
    the handle is still in the text but no longer sits in the sentence that says what
    it is for. The mention is also not mistaken for the post's author link.
    """
    blocks = dom_blocks(_MENTION_HTML)
    assert [h for h, _ in blocks] == ["@lnkrnchk"]
    body = post_body(blocks[0][1])
    assert body == "Пишите @acme_hr, это наш HR."
    contact = detect_contact(body)
    assert contact is not None
    assert (contact.platform, contact.target) == ("telegram", "@acme_hr")


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


# A third party's post with 281 replies, i.e. a thread that cannot possibly fit in
# one render. The canary above proves the SELECTORS still work; this one proves the
# reader is not merely getting away with a short thread. Numbers measured 2026-07-27:
# 14 containers at goto+settle, 22 after scrolling. If @mosseri ever deletes it, put
# any public post with 30+ replies here — the assertions are about the delta, not
# about this post.
_LONG_URL = "https://www.threads.com/@mosseri/post/Dac8hv6lrYM"


@pytest.mark.live
def test_live_a_long_thread_is_only_read_whole_after_scrolling():
    """The one untested link in the core promise: goto + settle renders the TOP of
    a thread, and the author's self-replies — the only reason this module exists —
    sit below the root post.

    A failure here is most likely one of two things, in this order:
      * rate limiting. Repeated anonymous loads of the same post get a gated view
        (root only, replies behind a "Log in or sign up" interstitial, count near
        zero). It clears after several minutes. `before` will be tiny.
      * Meta changed the scroll container, so `_SCROLL_JS` finds nothing to scroll
        and `after == before`. Then the fix is in `_SCROLL_JS`, not here.
    """
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_context().new_page()
            page.goto(_LONG_URL, timeout=45000, wait_until="domcontentloaded")
            page.wait_for_timeout(_SETTLE_MS)
            before = page.evaluate(_COUNT_JS)
            after = load_whole_thread(page)
        finally:
            browser.close()

    assert before >= 5, (
        f"only {before} posts rendered before scrolling — this is what a rate-limited "
        "anonymous view looks like; wait several minutes and re-run before touching "
        "the selectors")
    assert after > before, (
        f"scrolling loaded nothing ({before} -> {after}) on a 281-reply thread: either "
        "Meta changed the scroll container or the whole thread now arrives at once")
    assert after >= 15, (
        f"only {after} posts after scrolling (measured 22 on 2026-07-27) — the "
        "anonymous ceiling moved, or the thread was gated mid-read")
