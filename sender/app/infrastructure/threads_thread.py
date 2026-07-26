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
#  * a post block = the nearest ancestor of that link holding real text;
#  * the whole-thread wrapper matches too (it starts with «Ветка … просмотров»), so
#    any block that CONTAINS another block is dropped;
#  * the body sits in `span[dir="auto"]`, split one span per paragraph. Taking only
#    the longest span drops the opening paragraphs, so every leaf span is collected
#    in DOM order; spans inside the author link are skipped (they are the handle).
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
    if (b.closest('span[dir="auto"]')) b.remove();   // translate link, "… ещё"
  }

  const blocks = [], seen = new Set();
  for (const a of document.querySelectorAll('a[href^="/@"]')) {
    let el = a, hops = 0, b = null;
    while (el && hops < 6) {
      if ((el.innerText || '').trim().length > 40) { b = el; break; }
      el = el.parentElement; hops++;
    }
    if (b && !seen.has(b)) {
      seen.add(b);
      blocks.push({ el: b, handle: a.getAttribute('href').split('/')[1] });
    }
  }
  const kept = blocks.filter(x => !blocks.some(y => y !== x && x.el.contains(y.el)));
  return kept.map(({ el, handle }) => {
    const spans = [...el.querySelectorAll('span[dir="auto"]')].filter(s =>
      !s.querySelector('span[dir="auto"]')
      && !s.closest('a[href^="/@"]')
      && !s.closest('[role="button"], button'));
    const parts = [];
    for (const s of spans) {
      const t = (s.innerText || '').trim();
      if (t && !parts.includes(t)) parts.push(t);
    }
    return [handle, parts];
  });
}
"""


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
        blocks = read_thread_blocks(page)
    except Exception:  # noqa: BLE001 — an unreadable thread is not a lost lead
        return ""
    return author_thread_text(blocks, author)


def render_thread(url: str, headless: bool = True) -> str:
    """Open an anonymous browser, read the thread, close it. "" on any failure."""
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
