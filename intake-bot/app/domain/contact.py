"""Deterministic detection of (platform, target) from free vacancy text.

Priority order: telegram > email > linkedin > hh > wellfound > threads. The first
rule that matches wins. Platform detection is rule-based on purpose: it decides
where the message is later sent, so it must not depend on an LLM guess.

Threads is deliberately last: a recruiter who drops a thread link next to their own
@nick or e-mail is reachable there directly, and a direct channel beats a public
post. Only the post author's own handle is exempt (see detect_contact).
"""
import re
from dataclasses import dataclass


@dataclass
class Contact:
    platform: str   # telegram | email | linkedin | hh | wellfound | threads
    target: str     # @nick / t.me URL / email / profile or vacancy URL


# t.me / telegram.me links (scheme optional).
_TME_RE = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/\w{3,}", re.IGNORECASE)
# A Telegram @handle anchored to start-or-whitespace, so it never matches the
# "@" inside an email address (e.g. john@gmail.com).
_HANDLE_RE = re.compile(r"(?:^|\s)@(\w{4,})\b")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_LINKEDIN_RE = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/\S+", re.IGNORECASE)
# HeadHunter runs one network across national domains (hh.kz, hh.uz, …) and the
# regional subdomains under them (astana.hh.kz). Vacancy ids are shared network-wide.
_HH_HOST = r"(?:[\w.-]*\.)?hh\.(?:ru|kz|uz|by|kg|az|tj)"
# A vacancy link is matched first and separately: the iOS share sheet sends
#   "Vacancy: https://hh.kz/vacancy/135297431  … Sent via hh mobile app https://hh.ru/mobile"
# so a rule that takes any hh link would store the app-download footer as the target.
_HH_VACANCY_RE = re.compile(rf"(?:https?://)?{_HH_HOST}/vacancy/\d+\S*", re.IGNORECASE)
_HH_RE = re.compile(rf"(?:https?://)?{_HH_HOST}/\S+", re.IGNORECASE)
_WELLFOUND_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:wellfound\.com|angel\.co)/\S+", re.IGNORECASE)

# Threads (Meta). Posts live at /@user/post/<id>. threads.net is an alias that
# 301s to threads.com (verified 2026-07-26: identical bytes), so it is folded onto
# .com — the sender opens exactly what the sheet holds. The iOS/Android share sheet
# appends a tracking blob (?xmt=…&slof=1) that is noise for us. The left boundary
# keeps the host from matching inside a look-alike one (notthreads.com), which would
# otherwise be canonicalised into a threads.com URL nobody ever sent.
_THREADS_HOST = r"(?:www\.)?threads\.(?:com|net)"
_THREADS_RE = re.compile(
    rf"(?<![\w.-])(?:https?://)?{_THREADS_HOST}/@[\w.]+/post/[\w-]+\S*", re.IGNORECASE)
_THREADS_PARTS_RE = re.compile(
    rf"^(?:https?://)?{_THREADS_HOST}/@([\w.]+)/post/([\w-]+)", re.IGNORECASE)
# A Threads handle may contain dots (the namespace is Instagram's), while _HANDLE_RE
# captures `\w{4,}` and stops at the first one: the author "@ivan.hr" would reach the
# exemption below as "@ivan". This yields the whole dotted token at a match position,
# which the exemption compares alongside the capture itself.
_HANDLE_TOKEN_RE = re.compile(r"[\w.]+")


def canonical_threads_url(url: str) -> str:
    """A shared Threads link -> the plain post URL the sender can open."""
    m = _THREADS_PARTS_RE.match(url)
    if not m:
        return url
    return f"https://www.threads.com/@{m.group(1)}/post/{m.group(2)}"


def threads_author(url: str) -> str:
    """'@handle' of the post author from the URL, or '' when it is not a Threads
    post link. Authoritative author comes from the rendered page in the sender;
    this is what the intake has to work with."""
    m = _THREADS_PARTS_RE.match(url)
    return "@" + m.group(1) if m else ""


_TRAILING = ".,);]>\"'"


def _clean(url: str) -> str:
    return url.rstrip(_TRAILING)


# Vacancy id out of any HeadHunter link: national domain, regional subdomain, and
# whatever tracking the sharer appended.
_HH_VACANCY_ID_RE = re.compile(rf"^(?:https?://)?{_HH_HOST}/vacancy/(\d+)", re.IGNORECASE)
_HH_REGIONAL_RE = re.compile(
    r"^(?:https?://)?(?:[\w.-]*\.)?hh\.(?:kz|uz|by|kg|az|tj)/", re.IGNORECASE)


def canonical_hh_url(url: str) -> str:
    """A shared HeadHunter link -> the plain desktop URL the sender can open.

    Phone shares arrive as `https://astana.hh.kz/vacancy/135297431?from=share_ios`.
    Two things are wrong with that for us: the tracking tail is noise, and the
    browser session from `make login_hh` is hh.ru-only — cookies don't cross to a
    national domain, so a regional link browses anonymously and dead-ends at the
    login wall on Apply. Vacancy ids are shared across the whole network, so the
    same id on hh.ru is the same vacancy, opened logged in.
    """
    m = _HH_VACANCY_ID_RE.match(url)
    if m:
        return f"https://hh.ru/vacancy/{m.group(1)}"
    return _HH_REGIONAL_RE.sub("https://hh.ru/", url, count=1)


def detect_contact(text: str) -> Contact | None:
    # The Threads link is located up front, but only to protect its author handle:
    # "вакансия от @lnkrnchk <threads link>" would otherwise match _HANDLE_RE and
    # be stored as a Telegram contact, and the send loop would DM a user that does
    # not exist there. A DIFFERENT @handle still wins, as it always did — and every
    # handle is scanned, not just the first, because the message may credit the author
    # before it gives the real contact ("вакансия от @lnkrnchk, пиши @ivan_hr") just
    # as easily as after it. Only a message whose every handle is the author falls
    # through to threads.
    tm = _THREADS_RE.search(text)
    threads_url = canonical_threads_url(_clean(tm.group(0))) if tm else ""
    author = threads_author(threads_url).lower()

    m = _TME_RE.search(text)
    if m:
        return Contact("telegram", _clean(m.group(0)))
    for m in _HANDLE_RE.finditer(text):
        # The author is recognised in either shape, and BOTH clauses are load-bearing.
        # A prefix test in their place would be wrong: it swallows "@lnkrnchk_hr", who
        # is a different person from the author "@lnkrnchk".
        #   token   — _HANDLE_RE stops at a dot, so the author "@ivan.hr" arrives here
        #             truncated to "@ivan"; the whole token is what identifies him, and
        #             storing the truncation would DM an unrelated real user.
        #   capture — a dot glued to the author's handle ("@lnkrnchk.hr", or a period
        #             with no space after it: "@lnkrnchk.Пиши") makes the token differ
        #             from the author while the capture still is exactly the author —
        #             and that handle was never written in the message. Not redundant:
        #             deleting this clause reintroduces the fabricated target.
        #   author. — the mirror of the clause above, for a DOTTED author: in
        #             "вакансия от @ivan.hr.Пиши в личку" the token runs on into the
        #             next sentence ("ivan.hr.Пиши"), so it equals neither the author
        #             nor anything the capture ("@ivan") can catch, and "@ivan" — a
        #             real, unrelated Telegram user — was stored. The dot after the
        #             full author handle is what identifies him. It cannot over-match
        #             the way a bare prefix test would: "@lnkrnchk_hr" is a different
        #             person and there is no dot, so it still wins.
        # A trailing dot is sentence punctuation; a Threads handle cannot end in one.
        token = _HANDLE_TOKEN_RE.match(text, m.start(1)).group(0).rstrip(".")
        if author and (token.lower() == author[1:]
                       or token.lower().startswith(author[1:] + ".")
                       or ("@" + m.group(1)).lower() == author):
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
    if threads_url:
        return Contact("threads", threads_url)
    return None
