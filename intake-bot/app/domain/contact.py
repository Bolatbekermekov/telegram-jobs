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
# appends a tracking blob (?xmt=…&slof=1) that is noise for us.
_THREADS_HOST = r"(?:www\.)?threads\.(?:com|net)"
_THREADS_RE = re.compile(
    rf"(?:https?://)?{_THREADS_HOST}/@[\w.]+/post/[\w-]+\S*", re.IGNORECASE)
_THREADS_PARTS_RE = re.compile(
    rf"^(?:https?://)?{_THREADS_HOST}/@([\w.]+)/post/([\w-]+)", re.IGNORECASE)


def canonical_threads_url(url: str) -> str:
    """A shared Threads link -> the plain post URL the sender can open."""
    m = _THREADS_PARTS_RE.match(url)
    if not m:
        return url
    return f"https://www.threads.com/@{m.group(1)}/post/{m.group(2)}"


def threads_post_id(url: str) -> str:
    """The post id, which is the post's identity: a wrong @user with a right id
    still resolves to the same post (verified live 2026-07-26).

    Nothing calls this yet — the intake path has no dedup at all today (dedup lives
    only in the search path's candidates_repo), and adding it is out of scope. It
    exists because canonicalisation is the hard half of dedup and doing it here
    costs nothing.
    """
    m = _THREADS_PARTS_RE.match(url)
    return m.group(2) if m else ""


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
        handle = "@" + m.group(1)
        if handle.lower() != author:
            return Contact("telegram", handle)
    m = _EMAIL_RE.search(text)
    if m:
        return Contact("email", m.group(0))
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
