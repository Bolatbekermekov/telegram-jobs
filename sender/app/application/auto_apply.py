"""Pure mapping: form fields + ApplyProfile -> concrete fill actions.

Deterministic facts come from the profile; free-text questions are flagged
needs_ai for a later, injected answerer (see answer_ai_fields, added next).
No Playwright, no network — fully testable.
"""
import re
from dataclasses import dataclass, field

from app.domain.apply_profile import ApplyProfile
from app.domain.page_observation import FieldObs, PageObservation

EEO_ANSWER = "Prefer not to say"

_SKIP_FILL_RE = re.compile(r"cookie|newsletter|subscrib|\bsearch\b", re.I)

# label/name regex -> resolver(profile) -> value ("" means "no fact, skip rule").
_LABEL_RULES = [
    (re.compile(r"e-?mail", re.I), lambda p: p.email),
    (re.compile(r"phone|mobile|\btel\b", re.I), lambda p: p.phone),
    (re.compile(r"first name|given name", re.I), lambda p: p.first_name),
    (re.compile(r"last name|surname|family name", re.I), lambda p: p.last_name),
    (re.compile(r"full name|your name|\bname\b", re.I), lambda p: p.full_name),
    (re.compile(r"linkedin", re.I), lambda p: p.linkedin),
    (re.compile(r"github", re.I), lambda p: p.github),
    (re.compile(r"portfolio|personal website|website|\burl\b", re.I), lambda p: p.portfolio),
    (re.compile(r"\bcity\b|town", re.I), lambda p: p.city),
    (re.compile(r"country", re.I), lambda p: p.country),
    (re.compile(r"location|where are you", re.I),
     lambda p: ", ".join(x for x in (p.city, p.country) if x)),
    (re.compile(r"salary|compensation|expected pay|\brate\b", re.I), lambda p: p.desired_salary),
    (re.compile(r"notice period|availability|start date", re.I), lambda p: p.notice_period),
]


@dataclass
class FillAction:
    field: FieldObs
    value: str = ""                 # text value, file path, or chosen option text
    choice_index: int | None = None
    is_file: bool = False
    needs_ai: bool = False
    source: str = "unmapped"        # profile | cv | eeo | custom | ai | unmapped


def _satisfied(a: FillAction) -> bool:
    if a.is_file:
        return bool(a.value)
    if a.choice_index is not None:
        return True
    return bool(a.value.strip()) and "[" not in a.value


@dataclass
class ApplyPlan:
    actions: list[FillAction] = field(default_factory=list)

    @property
    def ai_fields(self) -> list[FillAction]:
        return [a for a in self.actions if a.needs_ai]

    def unmapped_required(self) -> list[str]:
        return [a.field.label or a.field.name
                for a in self.actions if a.field.required and not _satisfied(a)]

    def ready_to_submit(self) -> bool:
        return not self.unmapped_required()


def is_fillable_field(f: FieldObs) -> bool:
    """Wider than classify.is_real_field: keep consent/agreement checkboxes (we may
    need to tick them), drop only cookie-banner/newsletter/search noise."""
    if f.type in ("hidden", "submit", "button", "reset", "image"):
        return False
    if _SKIP_FILL_RE.search(f"{f.label} {f.name}"):
        return False
    return True


def _match_choice(options: list[str], *wants: str) -> int | None:
    for i, opt in enumerate(options):
        low = opt.lower()
        if any(w in low for w in wants):
            return i
    return None


def _yes_no(f: FieldObs, yes: bool, source: str = "profile") -> FillAction:
    if f.options:
        idx = _match_choice(f.options, "yes" if yes else "no")
        if idx is not None:
            return FillAction(field=f, choice_index=idx, value=f.options[idx], source=source)
    return FillAction(field=f, value="Yes" if yes else "No", source=source)


def map_field(f: FieldObs, profile: ApplyProfile, cv_path: str) -> FillAction:
    low = f"{f.label} {f.name}".strip().lower()

    if f.type == "file":
        return FillAction(field=f, value=cv_path, is_file=True, source="cv")

    if re.search(r"gender|race|ethnic|veteran|disabilit|sexual orientation|pronoun", low):
        if f.options:
            idx = _match_choice(f.options, "prefer not", "decline", "not to say")
            if idx is None:
                idx = len(f.options) - 1
            return FillAction(field=f, choice_index=idx, value=f.options[idx], source="eeo")
        return FillAction(field=f, value=EEO_ANSWER, source="eeo")

    if re.search(r"sponsor|visa", low):
        return _yes_no(f, profile.needs_visa_sponsorship)
    if re.search(r"authori[sz]ed to work|work authori|eligible to work|right to work", low):
        return _yes_no(f, not profile.needs_visa_sponsorship)
    if re.search(r"relocat", low):
        return _yes_no(f, profile.open_to_relocation)

    if f.type == "checkbox":
        if re.search(r"agree|consent|privacy|terms|policy|gdpr|authori", low):
            return FillAction(field=f, value="true", source="profile")
        return FillAction(field=f, value="", source="unmapped")

    for key, ans in profile.custom_answers.items():
        if key and key in low:
            if ans:
                return FillAction(field=f, value=ans, source="custom")
            return FillAction(field=f, needs_ai=True, source="ai")

    for rx, resolver in _LABEL_RULES:
        if rx.search(low):
            val = resolver(profile)
            if val:
                return FillAction(field=f, value=val, source="profile")

    if f.tag == "textarea" or re.search(r"why|cover|message|about|motivat|tell us", low):
        return FillAction(field=f, needs_ai=True, source="ai")
    if f.options:                       # unknown select/radio -> let the AI pick
        return FillAction(field=f, needs_ai=True, source="ai")
    if f.tag == "input" and f.type in ("text", "", "url", "number"):
        return FillAction(field=f, needs_ai=True, source="ai")

    return FillAction(field=f, source="unmapped")


def build_plan(obs: PageObservation, profile: ApplyProfile, cv_path: str) -> ApplyPlan:
    actions = [map_field(f, profile, cv_path)
               for f in obs.fields if is_fillable_field(f)]
    return ApplyPlan(actions=actions)
