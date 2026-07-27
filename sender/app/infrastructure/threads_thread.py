"""Reading a whole Threads thread in a browser.

Why a browser at all: `og:description` (what the intake bot reads over plain HTTP)
carries the ROOT post only. The second half of the requirements and the contact to
apply to live in the author's self-replies, which are absent from the anonymous
HTML entirely — verified 2026-07-26, zero occurrences of the contact handle in
545 KB of server-rendered markup, three in the 933 KB the browser renders.

This renders ANONYMOUSLY: no storage_state, no session. Reading a public post is
not an action that needs an account, so the resolve path carries none of the ban
risk that posting from a logged-in Threads account does. Only ThreadsChannel (the
DM fallback) touches the saved session.

DOM interaction is isolated here on purpose, the same way channels/linkedin.py
isolates its selectors: they drift. The decision of what IS the vacancy is pure
and lives in domain/threads_post.py.
"""
import re

from app.domain.threads_post import author_thread_text

_AUTHOR_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?threads\.(?:com|net)/@([\w.]+)/post/[\w-]+",
    re.IGNORECASE)

# Wait for the thread to hydrate. The posts are client-rendered, so a goto() that
# resolves is not a page that has content yet.
_SETTLE_MS = 2500
_GOTO_TIMEOUT_MS = 30000

# Verified live 2026-07-26 on threads.com/@lnkrnchk/post/DbL4LxBl6v9 and on a
# profile feed. Anchored on semantics, not on Meta's generated class names
# (`x1a6qonq x6ikm8r …`), which change without notice:
#
#  * every post carries an author link `a[href^="/@"]` -> that is the handle, and it
#    is locale-independent (unlike the «Автор»/"Author" badge);
#  * a post block = `a.closest('[data-pressable-container]')`. Threads marks every
#    post card with that attribute, exactly one per card: measured on the target
#    thread, 10 containers for the 10 posts rendered at the time, none nested; on a
#    profile feed, 16 for 15 posts plus 1 quoted card. (The same thread yields 13
#    once scrolled — see _SCROLL_JS below. The ratio is what was measured here, not
#    the total.) The whole-thread wrapper («Ветка … просмотров») is NOT a pressable
#    container, so it can no longer be picked up at all;
#  * quote posts DO nest one card inside another. The outer card is the author's own
#    post and the inner one is what they quoted, so any block CONTAINED by another
#    block is dropped. Measured on @mosseri's feed, keeping the inner card instead
#    returned «@zuck» with an empty body and lost mosseri's own text entirely;
#  * keeping the outer card is only half of it — the span query is scoped to the card
#    it belongs to (`s.closest('[data-pressable-container]') === el`), because
#    querySelectorAll on the outer card also reaches into the nested one. Unscoped,
#    the quoted post's body is collected as the AUTHOR's text, and the handle filter
#    in author_thread_text cannot help: the block really is the author's. A stranger's
#    «пишите мне @stranger_hr» would then be read as the vacancy's own contact and the
#    outreach would go to them. It also defeats the source-text check Task 8 plans
#    against invented handles, since the stranger's handle IS in the source text;
#  * the body sits in `span[dir="auto"]`, split one span per paragraph. Taking only
#    the longest span drops the opening paragraphs, so every leaf span is collected
#    in DOM order; spans inside the author link are skipped (they are the handle).
#
# NOT a length threshold, and do not reintroduce one. The first version climbed to
# the nearest ancestor whose innerText ran past 40 characters, which was only ever a
# crude way of stepping over the header row — it was never a property of a post, and
# it dropped short posts outright and silently. Measured hop by hop from the avatar
# link, innerText length per hop:
#
#     /@lnkrnchk    [0, 0, 0, 508]         -> found
#     /@khamartdil  [0, 0, 0, 21, 21, 21]  -> never found («Лучшие!»)
#     /@maxlanies   [0, 0, 0, 22, 22, 22]  -> never found («Покажешь?»)
#
# The climb PLATEAUS at the post, so allowing more hops would not have helped; the
# threshold itself was the bug, and a terse self-reply is exactly the shape a contact
# arrives in («тг: @nick»). Lowering the threshold does not work either, and neither
# does the obvious structural substitute «nearest ancestor that holds a body span»:
# that ancestor is the HEADER row, measured at 18 / 27 / 13 characters for these
# posts («lnkrnchk\nhiring\n1d»), and since the header sits INSIDE the post it would
# win the containment filter and replace every body with its own chrome.
#
# The failure mode this trades into: if Meta renames the attribute, `closest` returns
# null for every anchor, no block is emitted and resolve_thread returns "" — the lead
# keeps the 480 chars the intake already stored. Verified by stripping the attribute
# from the live page: [] blocks, "" text, no exception. Every lead degrading at once
# is easier to notice than one post quietly missing from one thread, but nothing
# offline can catch it; the live canary in tests/test_threads_thread.py is what does.
#
# Two things are pruned from the DOM before anything is read, because no rule on the
# resulting TEXT can undo them:
#
#  1. A mention is an anchor, and Threads wraps it in block-level <div>s:
#         <span dir="auto"><span>Spotlight: </span>
#           <div><span><div><a href="/@nick"><span>@nick</span></a></div></span></div>
#           <span>. LJ is …</span></span>
#     so innerText comes back as "Spotlight: \n@nick\n. LJ is …" — the handle torn
#     out of its sentence. `textContent` on that same span returns it glued, but it
#     cannot be used instead: innerText is what preserves the line breaks between
#     bullet points («Что предстоит делать:\n— развивать…»), and textContent
#     collapses them into one unreadable run. So the anchor's wrapper is replaced by
#     a plain text node and innerText is kept everywhere. Only anchors are touched,
#     so prose that merely contains an at-sign («разработчик @ Astana») is untouched.
#  2. Controls. The translate link sits INSIDE the body span, so its label arrives
#     glued to the last line of the vacancy («…в Telegram: @ nick  \nTranslate») —
#     multi-word, so domain/threads_post.py cannot drop it by shape. The engagement
#     counters sit in sibling `[role="button"]`s, and their abbreviated forms
#     («1.2K», «1,2 тыс.») are not numeric by shape either, so they shield the whole
#     counter row into the body — measured on a viral post. Both are excluded here,
#     at the DOM level, where they are unambiguously interface and not text.
_READ_BLOCKS_JS = """
() => {
  for (const a of document.querySelectorAll('a[href^="/@"]')) {
    const href = a.getAttribute('href') || '';
    if (href.includes('/post/')) continue;      // timestamp permalink, not a mention
    const body = a.closest('span[dir="auto"]');
    if (!body) continue;                        // the author link in a post header
    const glued = (a.textContent || '').trim();
    if (!glued) continue;
    let top = a;
    while (top.parentElement && top.parentElement !== body
           && (top.parentElement.textContent || '').trim() === glued) {
      top = top.parentElement;                  // climb out of the wrapper divs
    }
    top.replaceWith(document.createTextNode(glued));
  }
  for (const b of document.querySelectorAll('[role="button"], button')) {
    // parentElement first: closest() matches the element itself, so a body span that
    // is ITSELF pressable would otherwise be deleted outright. Measured: this bounds
    // the damage — the node survives — but it does NOT rescue the text, because the
    // span filter below self-matches the same way and skips it anyway. Loosening that
    // one instead would let «Показать перевод» back in as body text, so it stays as
    // it is: for a span we cannot tell from a control, skipping beats destroying.
    if (b.parentElement && b.parentElement.closest('span[dir="auto"]')) b.remove();
  }

  const blocks = [], seen = new Set();
  for (const a of document.querySelectorAll('a[href^="/@"]')) {
    const b = a.closest('[data-pressable-container]');
    if (b && !seen.has(b)) {
      seen.add(b);
      blocks.push({ el: b, handle: a.getAttribute('href').split('/')[1] });
    }
  }
  const kept = blocks.filter(x => !blocks.some(y => y !== x && y.el.contains(x.el)));
  return kept.map(({ el, handle }) => {
    const spans = [...el.querySelectorAll('span[dir="auto"]')].filter(s =>
      !s.querySelector('span[dir="auto"]')
      && !s.closest('a[href^="/@"]')
      && !s.closest('[role="button"], button')
      && s.closest('[data-pressable-container]') === el);  // not the quoted card's
    const parts = [];
    for (const s of spans) {
      const t = (s.innerText || '').trim();
      if (t && !parts.includes(t)) parts.push(t);
    }
    return [handle, parts];
  });
}
"""


# Threads PAGINATES a thread on scroll, and it does not scroll the window: the posts
# live inside an overflow container (`div#scrollview` at the time of writing), so
# `window.scrollTo` and a wheel event over the document are both no-ops — the count
# never moves. Hence the walk from a post card up to its first scrollable ancestor:
# semantic, not pinned to Meta's generated id, and it degrades to
# `document.scrollingElement` if the card attribute is ever renamed.
#
# Measured live and anonymously 2026-07-27 — goto+2500ms (what this used to do) vs
# the same page scrolled to the bottom, counting [data-pressable-container]:
#
#     @mosseri/post/Dac8hv6lrYM   (281 replies)   14 -> 22
#     @lnkrnchk/post/DbL4LxBl6v9  (the canary)     8 -> 13
#
# and the control is what makes it pagination rather than slow hydration: on the
# first thread, waiting 32 s WITHOUT scrolling left the count at 14 for every one of
# 21 samples. Under-reading matters here specifically because the author's own
# self-replies — the only reason this module exists — sit BELOW the root post.
#
# What this does NOT do is defeat the anonymous ceiling: a dozen or so replies in,
# Threads puts a "Log in or sign up" interstitial under the thread and stops serving
# more, and no amount of scrolling moves that. The loop takes everything the
# anonymous view is willing to render and stops when the count stops growing.
_SCROLL_JS = """
() => {
  let sc = document.querySelector('[data-pressable-container]');
  while (sc && !(sc.scrollHeight > sc.clientHeight + 50
                 && /auto|scroll/.test(getComputedStyle(sc).overflowY))) {
    sc = sc.parentElement;
  }
  (sc || document.scrollingElement).scrollTop = 1e9;
  window.scrollTo(0, document.documentElement.scrollHeight);
}
"""
_COUNT_JS = "() => document.querySelectorAll('[data-pressable-container]').length"

# Bounded on purpose: the send loop pays this per lead. Two rounds is the normal
# cost (one that loads, one that proves nothing more came), i.e. ~2.4 s.
_SCROLL_ROUNDS = 6
_SCROLL_SETTLE_MS = 1200


def author_from_url(url: str) -> str:
    """'@handle' of the post author from the post URL, or '' if not a post URL."""
    m = _AUTHOR_RE.match((url or "").strip())
    return "@" + m.group(1) if m else ""


def read_thread_blocks(page) -> list[tuple[str, list[str]]]:
    """[(handle, span_texts)] for every post on the page, in document order."""
    raw = page.evaluate(_READ_BLOCKS_JS) or []
    blocks = []
    for row in raw:
        # The page is not ours; never trust its shape.
        if not isinstance(row, (list, tuple)) or len(row) != 2:
            continue
        handle, parts = row
        if not isinstance(handle, str) or not isinstance(parts, list):
            continue
        blocks.append((handle, [p for p in parts if isinstance(p, str)]))
    return blocks


def load_whole_thread(page) -> int:
    """Scroll to the bottom until the post count stops growing. Returns that count.

    Bounded twice — by `_SCROLL_ROUNDS` and by the count going flat — because the
    page is not ours and an infinite feed would otherwise never end the loop.
    """
    seen = -1
    for _ in range(_SCROLL_ROUNDS):
        page.evaluate(_SCROLL_JS)
        page.wait_for_timeout(_SCROLL_SETTLE_MS)
        n = page.evaluate(_COUNT_JS)
        # The page is not ours; never trust its shape. A non-int here must end the
        # loop, not raise: resolve_thread's except would swallow it into "", turning
        # a scroll that could not be counted into a lead with no vacancy text.
        if not isinstance(n, int) or n <= seen:
            break
        seen = n
    return max(seen, 0)


def resolve_thread(page, url: str) -> str:
    """The author's own posts in `url`, joined, or "" if the thread can't be read.

    Never raises: a login wall, a timeout, a detached frame or a layout change all
    mean the caller keeps whatever text the intake already stored.
    """
    author = author_from_url(url)
    if not author:
        return ""
    try:
        page.goto(url, timeout=_GOTO_TIMEOUT_MS, wait_until="domcontentloaded")
        page.wait_for_timeout(_SETTLE_MS)
        load_whole_thread(page)
        # Assembly stays inside the try as well, so the never-raise contract does not
        # depend on how another module behaves on a shape neither of us predicted.
        return author_thread_text(read_thread_blocks(page), author)
    except Exception:  # noqa: BLE001 — an unreadable thread is not a lost lead
        return ""


def render_thread(url: str, headless: bool = True) -> str:
    """Open an anonymous browser, read the thread, close it. "" on any failure."""
    # Checked before the browser starts: the send loop calls this per lead, and a
    # lead that is not a Threads post must not cost a browser launch.
    if not author_from_url(url):
        return ""

    from playwright.sync_api import sync_playwright

    pw = browser = None
    try:
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=headless)
        # No storage_state: this is a public read, it must not touch the session.
        page = browser.new_context().new_page()
        return resolve_thread(page, url)
    except Exception:  # noqa: BLE001
        return ""
    finally:
        if browser:
            try:
                browser.close()
            except Exception:  # noqa: BLE001
                pass
        if pw:
            try:
                pw.stop()
            except Exception:  # noqa: BLE001
                pass
