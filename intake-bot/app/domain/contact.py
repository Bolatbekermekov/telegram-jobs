"""Deterministic detection of (platform, target) from free vacancy text.

Priority order: telegram > email > linkedin > hh > wellfound. The first rule
that matches wins. Platform detection is rule-based on purpose: it decides where
the message is later sent, so it must not depend on an LLM guess.
"""
import re
from dataclasses import dataclass


@dataclass
class Contact:
    platform: str   # telegram | email | linkedin | hh | wellfound
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
