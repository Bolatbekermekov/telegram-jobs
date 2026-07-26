"""Assembling a Threads thread's vacancy text out of what the DOM hands us.

Pure by design: the DOM reading lives in infrastructure/threads_thread.py, so the
part that decides what IS the vacancy stays testable on recorded span texts.

A Threads vacancy is a thread, not a post: the root post carries the opening, and
the author continues in self-replies — that is where the second half of the
requirements and, crucially, the contact to apply to live. Other people's replies
in the same thread are trolling and other candidates' CVs, and must never be mixed
into the vacancy text.

Known limitation: a bare figure that ENDS a post — a salary, a headcount — is lost,
because by shape it is exactly an engagement counter, and a positional rule
("counters form a run at the very end") does not separate the two either. So
«Зарплата:» / «300 000» keeps the label and drops the number. Accepted rather than
guessed at: intake already stores the root post's og:description, which usually
carries the salary, so the cost is a thinner summary, not a missing fact.
"""
import re

# Engagement counters under a post: likes / replies / reposts. Always numeric, and
# Threads groups thousands with a thin space ("3 438").
_COUNTER_RE = re.compile(r"^[\d\s  .,]+$")
# A relative timestamp: "1 дн.", "2h", "15 мин", "3 d".
_TIME_RE = re.compile(r"^\d+\s*[^\W\d_]{1,5}\.?$", re.UNICODE)
_SEPARATORS = {"·", "•", "|", "—", "-"}
# Sentence-ish punctuation: a chrome token never has it, a real line usually does.
_SENTENCE_CHARS = set(".!?:;,")
# A body line often opens with a list marker instead of a word.
_LIST_MARKERS = ("—", "–", "-", "•", "*", "→")
# Longest a chrome token can plausibly be ("hiring", "Автор", "Author", "1 дн.").
_CHROME_MAX_CHARS = 12
# Interface debris glued to a handle: a leading "@", a trailing "·". Edges only —
# see _same_handle for why the inside of a handle is left alone.
_HANDLE_EDGE_RE = re.compile(r"^\W+|\W+$")


def _is_chrome(part: str) -> bool:
    """True when `part` is interface furniture, not post text.

    Deliberately shape-based, not word-based: the author badge is localised
    («Автор» / "Author") and the profile tag is whatever the user typed, so
    matching on their text would break on the next account or UI language.
    """
    p = part.strip()
    if not p or p in _SEPARATORS:
        return True
    # An "@" is always content: a handle, a mention, an email. Threads' chrome —
    # badges, relative timestamps, separators, engagement counters — never carries
    # one, and the author's own handle span is excluded upstream by the DOM reader.
    # Without this, "@acme_hr" (8 chars, one word, no punctuation) reads as a short
    # chrome token and a trailing contact line is thrown away.
    if "@" in p:
        return False
    if _COUNTER_RE.match(p) or _TIME_RE.match(p):
        return True
    # A short single word with no sentence punctuation: the "hiring" profile tag,
    # the «Автор»/"Author" badge. A real body line is longer, punctuated, or opens
    # with a list marker.
    return (len(p) <= _CHROME_MAX_CHARS
            and " " not in p
            and not (set(p) & _SENTENCE_CHARS)
            and not p.startswith(_LIST_MARKERS))


def post_body(parts: list[str]) -> str:
    """Text of one post from its span texts, without the interface chrome.

    Leading chrome (profile tag, timestamp, separator, author badge) is dropped
    until the first real line; trailing chrome (engagement counters) is dropped
    from the end. Anything in between is kept verbatim — a bare number in the
    middle of a post is part of the text (a budget, a headcount), not a counter.
    """
    cleaned = [p.strip() for p in parts if p and p.strip()]
    start = 0
    while start < len(cleaned) and _is_chrome(cleaned[start]):
        start += 1
    end = len(cleaned)
    while end > start and _is_chrome(cleaned[end - 1]):
        end -= 1
    return "\n".join(cleaned[start:end])


def _same_handle(a: str, b: str) -> bool:
    """Compare two handles, ignoring case and the debris the DOM glues onto them.

    Only the EDGES are normalised — a leading "@", trailing separators, stray
    whitespace. A handle's inside is left alone on purpose: Threads handles may
    contain periods («john.doe»), and an impersonation account differs from the real
    one by exactly that, so folding punctuation away everywhere would let a
    stranger's replies into the vacancy text.
    """
    return _HANDLE_EDGE_RE.sub("", a).lower() == _HANDLE_EDGE_RE.sub("", b).lower()


def author_thread_text(blocks: list[tuple[str, list[str]]], author: str) -> str:
    """Vacancy text = the author's own posts, in thread order, joined.

    `blocks` is [(handle, span_texts)] in document order, as read off the page.
    Matching is on the handle, NOT on the localised «Автор» badge.
    """
    bodies = []
    for handle, parts in blocks:
        if not _same_handle(handle, author):
            continue
        body = post_body(parts)
        if body:
            bodies.append(body)
    return "\n\n".join(bodies)
