"""Deterministic detection of (platform, target) from free vacancy text.

Sender-side copy of the intake bot's rule set. The two apps are separate deploys
with their own requirements, and this project already duplicates domain code
across them on purpose (`sheets_repo.py`, `lead.py`) rather than carrying a shared
package — this follows that.

Used by the Threads resolver: a thread's own text is where the real contact lives
("Для отклика присылайте портфолио в Telegram: @skyluckwalker"), and finding it is
what lets a threads lead be sent through the existing Telegram/email channel.

There is deliberately NO `threads` rule here: by the time this runs the lead is
already threads, and the question is only what it should become instead.

Priority order: telegram > email > linkedin > hh > wellfound. Rule-based on
purpose: it decides where the message is sent, so it must not be an LLM guess.
"""
import re
from dataclasses import dataclass


@dataclass
class Contact:
    platform: str   # telegram | email | linkedin | hh | wellfound
    target: str     # @nick / t.me URL / email / profile or vacancy URL


_TME_RE = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/\w{3,}", re.IGNORECASE)
# A Telegram @handle anchored to start-or-whitespace, so it never matches the
# "@" inside an email address (e.g. john@gmail.com). That anchor is the only thing
# keeping a well-formed email out of this rule, which is second of six and so
# pre-empts email/linkedin/hh whenever it fires.
# Allowing a space after the at-sign (`@\s?`, for the "@ skyluckwalker" seen on a
# live Threads post) was tried here and reverted: it also matches the "at" of
# "hr @ acme.com" and "Role @ Company", fabricating an "@acme"/"@Company" target
# while the real contact sat later in the same text.
# Threads' own LINKIFIED mentions do reach this rule glued, and that is built and
# verified against the live page: the DOM reader unwraps the mention anchor before
# reading the text (infrastructure/threads_thread.py), which is what stops innerText
# tearing "@nick" onto a line of its own.
# An at-sign the AUTHOR typed with a space after it is a different thing and is NOT
# covered. Measured 2026-07-26: that space is in the post as Threads stores it
# (its own payload has linkified_in_app_url: null precisely because of it), so no
# reader-side fix exists — the DOM is faithful, there is nothing to unglue. Closing
# it needs a TEXT-level rule, and the only safe shape is a contextual one applied in
# the resolver — glue "@ nick" only where a telegram/тг cue sits just before it —
# never a blanket `@\s+` here, which is the revert above. That rule is deliberately
# unwritten pending a human decision, so such a handle stays undetected and
# _HANDLE_RE stays an exact copy of the intake's.
_HANDLE_RE = re.compile(r"(?:^|\s)@(\w{4,})\b")
# The capture above is `\w{4,}` and stops at the first dot, so "@maria.hr" arrives at
# the rule as "@maria" — a different, real user. This yields the WHOLE dotted token at
# a match position, which is what the rule needs to see to refuse it. (Dots are legal
# in a Threads/Instagram handle — that namespace is Instagram's — and illegal in a
# Telegram username, which is the whole basis for refusing.)
_HANDLE_TOKEN_RE = re.compile(r"[\w.]+")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_LINKEDIN_RE = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/\S+", re.IGNORECASE)
_HH_HOST = r"(?:[\w.-]*\.)?hh\.(?:ru|kz|uz|by|kg|az|tj)"
# A vacancy link is matched first and separately: the iOS share sheet sends
#   "Vacancy: https://hh.kz/vacancy/135297431  … Sent via hh mobile app https://hh.ru/mobile"
# so a rule that takes any hh link would store the app-download footer as the target.
_HH_VACANCY_RE = re.compile(rf"(?:https?://)?{_HH_HOST}/vacancy/\d+\S*", re.IGNORECASE)
_HH_RE = re.compile(rf"(?:https?://)?{_HH_HOST}/\S+", re.IGNORECASE)
_WELLFOUND_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:wellfound\.com|angel\.co)/\S+", re.IGNORECASE)

_TRAILING = ".,);]>\"'"


def _clean(url: str) -> str:
    return url.rstrip(_TRAILING)


_HH_VACANCY_ID_RE = re.compile(rf"^(?:https?://)?{_HH_HOST}/vacancy/(\d+)", re.IGNORECASE)
_HH_REGIONAL_RE = re.compile(
    r"^(?:https?://)?(?:[\w.-]*\.)?hh\.(?:kz|uz|by|kg|az|tj)/", re.IGNORECASE)


def canonical_hh_url(url: str) -> str:
    """A regional HeadHunter link -> the hh.ru URL the saved session can open.

    Kept in this copy on purpose: the browser session from `make login_hh` is
    hh.ru-only, cookies don't cross to a national domain, so a regional link
    browses anonymously and dead-ends at the login wall on Apply. A thread that
    says "откликнуться на hh.kz/vacancy/…" would walk straight into that.
    """
    m = _HH_VACANCY_ID_RE.match(url)
    if m:
        return f"https://hh.ru/vacancy/{m.group(1)}"
    return _HH_REGIONAL_RE.sub("https://hh.ru/", url, count=1)


def detect_contact(text: str) -> Contact | None:
    m = _TME_RE.search(text)
    if m:
        return Contact("telegram", _clean(m.group(0)))
    for m in _HANDLE_RE.finditer(text):
        # A Telegram username cannot contain a dot, so "@maria.hr" is provably not a
        # Telegram target — it is an Instagram/Threads handle, or a period whose space
        # the writer forgot. _HANDLE_RE captures `\w{4,}` and stops at the dot, so
        # returning the match would store "@maria": a real, unrelated user nobody
        # wrote in the thread. Refuse the whole handle and keep going — hence
        # `finditer`, so a real handle later in the same text still wins. If nothing
        # else answers, the lead keeps its Threads DM fallback, which is weak but at
        # least reaches the person who actually posted.
        # A TRAILING dot is sentence punctuation ("пиши @ivan.") and is stripped
        # first — that shape is a plain handle and still wins.
        # The intake's author exemption has no counterpart here on purpose: there is
        # no Threads rule and no post URL in this copy, so it never had an author to
        # exempt. Refusing dotted handles is NOT part of that exemption and must stay
        # mirrored — it is the same rule in both apps.
        token = _HANDLE_TOKEN_RE.match(text, m.start(1)).group(0).rstrip(".")
        if "." in token:
            continue
        return Contact("telegram", "@" + m.group(1))
    m = _EMAIL_RE.search(text)
    if m:
        # `_clean` like every sibling rule: _EMAIL_RE's tail class `[\w.-]+` eats the
        # period that ended the sentence, and "hr@acme.io." is what an MTA rejects at
        # RCPT TO — the lead lands `failed` and the recruiter is never written to.
        return Contact("email", _clean(m.group(0)))
    m = _LINKEDIN_RE.search(text)
    if m:
        return Contact("linkedin", _clean(m.group(0)))
    m = _HH_VACANCY_RE.search(text) or _HH_RE.search(text)
    if m:
        return Contact("hh", canonical_hh_url(_clean(m.group(0))))
    m = _WELLFOUND_RE.search(text)
    if m:
        return Contact("wellfound", _clean(m.group(0)))
    return None
