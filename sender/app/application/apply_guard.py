"""Guards between untrusted page content and an irreversible submit.

The vacancy text, the employer's screening questions and the field labels of a
third-party ATS all arrive from a page we don't control, and they reach the model
in the same message as the CV. A page can therefore ask the model to do something
other than answer the question — there is no way to make the model reliably tell
an instruction from data.

So these functions don't try to detect an injection. They constrain what an
injection can achieve: only known ATS hosts are auto-filled, and an answer that
carries the candidate's contact details never gets submitted.
"""
import re

# ATS vendors whose forms we understand. Everything else is filled by hand: the
# rules below can't cover a form we've never seen, and a page we don't recognise
# is exactly where an unexpected field layout would show up.
ALLOWED_APPLY_HOSTS = frozenset({
    # Vendors classify_apply already recognises inside an iframe; an IFRAME_ATS
    # route navigates into one of these, so they must be fillable by name.
    "comeet.co",
    "greenhouse.io", "boards.greenhouse.io", "job-boards.greenhouse.io",
    "lever.co", "jobs.lever.co",
    "ashbyhq.com", "jobs.ashbyhq.com",
    "workable.com", "apply.workable.com",
    "smartrecruiters.com", "jobs.smartrecruiters.com",
    "myworkdayjobs.com",
    "bamboohr.com",
    "teamtailor.com",
    "recruitee.com",
    "personio.de", "jobs.personio.de",
    "join.com",
    "breezy.hr",
    "jazzhr.com", "applytojob.com",
    "hh.ru",
    "wellfound.com",
    "linkedin.com",
})


def _registrable(host: str) -> str:
    """Last two labels of a host — `boards.greenhouse.io` -> `greenhouse.io`.

    Deliberately naive: it is only used as a *second* chance to match the
    allowlist, so a multi-part public suffix (`co.uk`) can at worst fail to
    match and send the lead to a manual apply.
    """
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def host_allowed(url: str, allowed=ALLOWED_APPLY_HOSTS) -> bool:
    """True when `url`'s host is an ATS we auto-fill.

    Matches the host itself, its registrable domain, and any subdomain of an
    allowed entry (`eu.myworkdayjobs.com`), so vendors that shard by region or
    customer work without listing every host.
    """
    from urllib.parse import urlsplit

    host = (urlsplit(url).hostname or "").lower().strip(".")
    if not host:
        return False
    if host in allowed or _registrable(host) in allowed:
        return True
    return any(host.endswith("." + a) for a in allowed)


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def leaked_secrets(text: str, profile) -> list[str]:
    """Names of the profile's contact details that `text` reproduces.

    A model answering "tell us about yourself" has no reason to restate the
    candidate's email or phone number — the ATS collects those in their own
    fields. When one shows up in free text, the likeliest cause is a page that
    asked for it, so the answer must not be submitted.
    """
    found = []
    low = (text or "").lower()

    email = (getattr(profile, "email", "") or "").strip().lower()
    if email and email in low:
        found.append("email")

    # Compare digits only: "+7 (700) 123-45-67" and "77001234567" are one number.
    phone = _digits(getattr(profile, "phone", ""))
    if len(phone) >= 7 and phone[-7:] in _digits(text):
        found.append("phone")

    for attr in ("linkedin", "github", "portfolio"):
        val = (getattr(profile, attr, "") or "").strip().lower()
        if len(val) >= 8 and val in low:
            found.append(attr)

    return found
