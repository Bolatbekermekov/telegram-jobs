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
# Allowing a space after the at-sign (`@\s?`, for the "@ skyluckwalker" that Threads
# renders) was tried here and reverted: it also matches the "at" of "hr @ acme.com"
# and "Role @ Company", fabricating an "@acme"/"@Company" target while the real
# contact sat later in the same text. Mentions are glued when the thread is
# assembled instead — see the Threads resolver.
_HANDLE_RE = re.compile(r"(?:^|\s)@(\w{4,})\b")
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
    m = _HANDLE_RE.search(text)
    if m:
        return Contact("telegram", "@" + m.group(1))
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
    return None
