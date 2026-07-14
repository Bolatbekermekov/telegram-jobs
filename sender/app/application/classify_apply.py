"""Pure classifier: a PageObservation -> one outreach Route.

Order matters: a CAPTCHA/login wall wins over everything (can't be automated);
a real fillable apply form wins over an embedded ATS iframe; a known-ATS iframe
wins over a bare mailto. Cookie/consent/search fields are ignored so a cookie
banner is never mistaken for an application form (learned live on superplay.co).
"""
import re

from app.domain.page_observation import FieldObs, PageObservation, Route

KNOWN_ATS_HOSTS = (
    "comeet.co", "greenhouse.io", "lever.co", "ashbyhq.com", "workable.com",
    "smartrecruiters.com", "teamtailor.com", "recruitee.com", "myworkdayjobs.com",
)

_IGNORE_RE = re.compile(r"cookie|consent|gdpr|newsletter|subscrib|\bsearch\b", re.I)
_APPLY_HINT_RE = re.compile(
    r"name|e-?mail|phone|resume|cv|cover|linkedin|github|portfolio|website|"
    r"salary|experience|first|last|address|city|country|why|message|about|motivat",
    re.I)


def is_real_field(f: FieldObs) -> bool:
    """A field that could belong to a genuine application form."""
    if f.type in ("hidden", "submit", "button", "reset", "image"):
        return False
    if _IGNORE_RE.search(f"{f.label} {f.name}"):
        return False
    return True


def looks_like_apply_form(real_fields: list[FieldObs], file_inputs: int) -> bool:
    if file_inputs > 0:
        return True
    for f in real_fields:
        if f.type in ("email", "tel", "file"):
            return True
        if f.tag in ("input", "textarea") and _APPLY_HINT_RE.search(f"{f.label} {f.name}"):
            return True
    return False


def known_ats_iframe(iframes: list[str]) -> str | None:
    for src in iframes:
        low = src.lower()
        if any(host in low for host in KNOWN_ATS_HOSTS):
            return src
    return None


def classify(obs: PageObservation) -> Route:
    if obs.captcha or obs.login_required:
        return Route.GATED
    real = [f for f in obs.fields if is_real_field(f)]
    if looks_like_apply_form(real, obs.file_inputs):
        return Route.FORM
    if known_ats_iframe(obs.iframes):
        return Route.IFRAME_ATS
    if obs.mailto_links:
        return Route.EMAIL
    return Route.NONE
