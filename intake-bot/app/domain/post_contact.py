"""Whom to write to about a LinkedIn hiring post, read out of the post's own text.

The post comes back from an anonymous read (infrastructure/vacancy_fetcher.py) as
the author's own words: «резюме в телеграм @acme_hr», «CV на hr@acme.io», or
neither. Turning that into the lead's recipient is not cosmetic — free LinkedIn
cannot message outside the first degree, so a lead left pointing at LinkedIn goes
out as a connect request to a stranger, while the same lead pointed at the Telegram
handle the author actually asked for lands in a DM the sender already knows how to
deliver.

Pure text handling, no network: undoing LinkedIn's link rewrite is injected, so
this stays testable without touching the site.
"""
import re

from app.domain.vacancy_text import is_lnkd_in_url, iter_urls

# The two channels a lead can be delivered to directly, in `detect_contact`'s own
# order (telegram first, then email). Everything else it answers — hh, linkedin,
# wellfound, threads — is a page rather than an address: reaching the person behind
# it costs a browser, a session, and on free LinkedIn a connect request that may
# never be accepted.
#
# Read twice, for two questions. Here: which of a POST's contacts may be taken —
# an hh or LinkedIn url inside a post is a reference, «вот похожая вакансия» or
# «мой профиль», and routing the lead to one would write to whoever that page
# belongs to instead of the person hiring. In `application/extract_lead.py`: whether
# the MESSAGE already named an address, in which case the post is not consulted.
DIRECT_PLATFORMS = ("telegram", "email")

# A post can carry a dozen links, and every rewrite undone is one more http request
# on a clock already spent reading the post and about to be spent summarising it.
_MAX_SHORTENERS = 2

# A post url embeds its author's public id in the slug:
#   /posts/<author-public-id>_<text-slug>-activity-<id>-<code>
# Twin of `sender/app/domain/candidate.py:post_author_profile_url`, which the sender
# uses to open the profile. Intake needs it to record, at ingest time, whom the lead
# actually points at.
_POST_AUTHOR_RE = re.compile(r"/posts/([^/_]+)_")


def post_author_profile_url(url: str) -> str | None:
    """The profile url of a post's author, or None when the slug carries no author
    (a company `/feed/update/…` share)."""
    m = _POST_AUTHOR_RE.search(url or "")
    if not m:
        return None
    return f"https://www.linkedin.com/in/{m.group(1)}/"


def _accepted(contact):
    """`contact` when it is a channel a post may be routed to, else None."""
    if contact is None or contact.platform not in DIRECT_PLATFORMS:
        return None
    return contact


def _shorteners(text: str) -> list[str]:
    """The first `_MAX_SHORTENERS` LinkedIn-rewritten links in `text`."""
    found = []
    for url in iter_urls(text):
        if is_lnkd_in_url(url):
            found.append(url)
            if len(found) == _MAX_SHORTENERS:
                break
    return found


def pick_post_contact(post_text: str, detect, resolve_link=None):
    """The telegram or email contact a post names, or None if it names neither.

    `detect(text) -> Contact | None` is `app.domain.contact.detect_contact`.
    `resolve_link(url) -> str` undoes the `lnkd.in` rewrite; it is consulted only
    when the post names nothing in plain text, because each call costs a request.

    None is the useful answer of the last branch, not a failure: the caller falls
    back to the post's own author, whereas a guess made here would send a message
    about this vacancy to someone who never posted it.
    """
    text = post_text or ""
    if not text.strip():
        return None

    contact = _accepted(detect(text))
    if contact is not None:
        return contact

    if resolve_link is None:
        return None
    for url in _shorteners(text):
        try:
            resolved = resolve_link(url)
        except Exception:  # noqa: BLE001 — an unreachable shortener costs the
            # contact, never the lead: the author fallback is still there.
            continue
        contact = _accepted(detect(resolved or ""))
        if contact is not None:
            return contact
    return None
