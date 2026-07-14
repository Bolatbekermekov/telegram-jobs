# External-Apply Autofill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a LinkedIn job has no Easy Apply, follow the external "Apply" link, classify the destination page, and auto-fill + submit the ATS form with AI (full-auto, with guardrails), routing mailto-only pages to the email channel and gated pages (CAPTCHA/login) to a manual-handoff notification.

**Architecture:** A pure classifier (`classify`) turns a scraped `PageObservation` into one of five routes (form / email / iframe_ats / gated / none). A pure mapper (`build_plan` + `answer_ai_fields`) turns a form + `ApplyProfile` into a `ApplyPlan` of concrete fill actions, deterministic where facts exist and AI-answered for free text. A thin Playwright driver (`external_apply`) scrapes, routes, fills, and submits. The LinkedIn channel hands off to it; results flow back through the existing `SendResult` → sheet-status → Telegram-notify path with a new `manual` outcome.

**Tech Stack:** Python 3.13 (venv at `sender/.venv`), Playwright (sync API), OpenAI (via existing `OpenAIMessageGenerator`), PyYAML (new), pytest.

## Global Constraints

- Python target 3.10+ (use modern typing: `str | None`, `list[FieldObs]`, `dict[str, str]`).
- Tests live in `sender/tests/`; run via `sender/.venv/Scripts/python.exe -m pytest sender/tests -v`.
- Reuse existing code — do NOT reimplement: `app/application/hh_questions.py` (`fill_plan`), `OpenAIMessageGenerator.answer_questions`, `app/infrastructure/channels/email_channel.py`, `app/infrastructure/cv_loader.py`, `app/application/generate_message.py::subject_for`, `registry._hh_answerer` pattern.
- Answerer contract (verbatim, from `registry._hh_answerer`): `answerer(questions, vacancy_context) -> {id: {"text": str} | {"choice": int}}`, where each question is `{"id": str, "type": "text"|"choice", "prompt": str, "options": list[str]}`.
- Full-auto safety (spec §9): never click Submit when a required field is unfilled or a value contains `[`; gated pages (CAPTCHA/login) are never attempted; `APPLY_DRY_RUN=true` fills but never submits.
- Real personal data lives in `sender/apply_profile.yml` (already created, gitignored). Never commit it. `apply_profile.yml.example` is the committed template.
- Automating LinkedIn/ATS violates ToS (accepted by user). Reuse existing `DAILY_SEND_LIMIT` / delays.
- Commit after every task with a `feat(external-apply):` / `test(external-apply):` / `chore(external-apply):` message.

**Source of truth:** `docs/superpowers/specs/2026-07-14-external-apply-autofill-design.md`.

---

### Task 1: Profile subsystem — dependency, config, `ApplyProfile`, loader

**Files:**
- Modify: `sender/requirements.txt`
- Modify: `sender/app/config.py`
- Create: `sender/app/domain/apply_profile.py`
- Create: `sender/app/infrastructure/apply_profile_loader.py`
- Test: `sender/tests/test_apply_profile_loader.py`

**Interfaces:**
- Produces: `ApplyProfile` dataclass; `load_apply_profile(path: str) -> ApplyProfile`; config `APPLY_PROFILE_PATH: str`, `APPLY_DRY_RUN: bool`, `EXTERNAL_APPLY_ENABLED: bool`.

- [ ] **Step 1: Add the YAML dependency and install it**

Add to `sender/requirements.txt` (new last line):
```
pyyaml==6.0.2
```
Run: `sender/.venv/Scripts/pip.exe install pyyaml==6.0.2`
Expected: `Successfully installed pyyaml-6.0.2`

- [ ] **Step 2: Create the `ApplyProfile` dataclass**

Create `sender/app/domain/apply_profile.py`:
```python
"""Canonical candidate facts used to fill external application forms.

Loaded from sender/apply_profile.yml (gitignored). Pure data — no I/O here.
"""
from dataclasses import dataclass, field


@dataclass
class ApplyProfile:
    full_name: str = ""
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    city: str = ""
    country: str = ""
    linkedin: str = ""
    github: str = ""
    portfolio: str = ""
    work_authorization: str = ""
    needs_visa_sponsorship: bool = False
    desired_salary: str = ""
    open_to_relocation: bool = False
    notice_period: str = ""
    # Keys are lowercase question substrings -> ready answers ("" => let the AI answer).
    custom_answers: dict[str, str] = field(default_factory=dict)
```

- [ ] **Step 3: Write the failing loader test**

Create `sender/tests/test_apply_profile_loader.py`:
```python
from app.domain.apply_profile import ApplyProfile
from app.infrastructure.apply_profile_loader import load_apply_profile


def test_missing_file_returns_empty_profile(tmp_path):
    prof = load_apply_profile(str(tmp_path / "nope.yml"))
    assert isinstance(prof, ApplyProfile)
    assert prof.email == "" and prof.custom_answers == {}


def test_loads_fields_bools_and_lowercased_custom_answers(tmp_path):
    p = tmp_path / "apply_profile.yml"
    p.write_text(
        'full_name: "Bolatbek Yermekov"\n'
        'email: "a@b.com"\n'
        'needs_visa_sponsorship: false\n'
        'open_to_relocation: true\n'
        'phone:\n'                       # null -> coerced to ""
        'custom_answers:\n'
        '  "Years Of Experience": 3\n'   # non-str value -> str, key -> lowercase
        '  "why do you want": ""\n',
        encoding="utf-8",
    )
    prof = load_apply_profile(str(p))
    assert prof.full_name == "Bolatbek Yermekov"
    assert prof.needs_visa_sponsorship is False and prof.open_to_relocation is True
    assert prof.phone == ""
    assert prof.custom_answers["years of experience"] == "3"
    assert prof.custom_answers["why do you want"] == ""


def test_ignores_unknown_keys(tmp_path):
    p = tmp_path / "apply_profile.yml"
    p.write_text('email: "a@b.com"\nbogus_key: "x"\n', encoding="utf-8")
    prof = load_apply_profile(str(p))
    assert prof.email == "a@b.com"
    assert not hasattr(prof, "bogus_key")
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_apply_profile_loader.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.infrastructure.apply_profile_loader'`

- [ ] **Step 5: Implement the loader**

Create `sender/app/infrastructure/apply_profile_loader.py`:
```python
"""Load ApplyProfile from a YAML file (sender/apply_profile.yml)."""
from dataclasses import fields
from pathlib import Path

import yaml

from app.domain.apply_profile import ApplyProfile

_STR_FIELDS = {f.name for f in fields(ApplyProfile)
               if f.type == "str" or f.name not in ("needs_visa_sponsorship",
                                                     "open_to_relocation", "custom_answers")}
_KNOWN = {f.name for f in fields(ApplyProfile)}


def load_apply_profile(path: str) -> ApplyProfile:
    p = Path(path)
    if not p.exists():
        return ApplyProfile()
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    known = {k: v for k, v in data.items() if k in _KNOWN}
    # Coerce str fields: null -> "".
    for name in _STR_FIELDS:
        if name in known and known[name] is None:
            known[name] = ""
    raw_ca = known.get("custom_answers") or {}
    known["custom_answers"] = {
        str(k).lower(): ("" if v is None else str(v)) for k, v in raw_ca.items()
    }
    return ApplyProfile(**known)
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_apply_profile_loader.py -v`
Expected: PASS (3 passed)

- [ ] **Step 7: Wire config**

In `sender/app/config.py`, after the `BROWSER_HEADLESS = ...` line (~line 84), add:
```python
# --- External-apply autofill (LinkedIn jobs whose only route is a company ATS) ---
EXTERNAL_APPLY_ENABLED = os.environ.get("EXTERNAL_APPLY_ENABLED", "true").lower() == "true"
# true = fill the form but DO NOT click Submit (dry run for obkatka).
APPLY_DRY_RUN = os.environ.get("APPLY_DRY_RUN", "false").lower() == "true"
APPLY_PROFILE_PATH = os.environ.get(
    "APPLY_PROFILE_PATH", str(_ROOT / "sender" / "apply_profile.yml"))
```

- [ ] **Step 8: Commit**

```bash
git add sender/requirements.txt sender/app/config.py sender/app/domain/apply_profile.py sender/app/infrastructure/apply_profile_loader.py sender/tests/test_apply_profile_loader.py
git commit -m "feat(external-apply): ApplyProfile + YAML loader + config"
```

---

### Task 2: Page observation types + classifier

**Files:**
- Create: `sender/app/domain/page_observation.py`
- Create: `sender/app/application/classify_apply.py`
- Test: `sender/tests/test_classify_apply.py`

**Interfaces:**
- Produces: `Route` (enum: FORM, EMAIL, IFRAME_ATS, GATED, NONE); `FieldObs(tag, type, label, name, required, options, ref)`; `PageObservation(url, fields, file_inputs, iframes, mailto_links, apply_buttons, captcha, login_required, text_excerpt)`; `is_real_field(f) -> bool`; `known_ats_iframe(iframes) -> str | None`; `classify(obs) -> Route`.

- [ ] **Step 1: Create the observation types**

Create `sender/app/domain/page_observation.py`:
```python
"""Serializable snapshot of an application page (also the classifier's input
and the test-fixture shape). Pure data — no Playwright here."""
from dataclasses import dataclass, field
from enum import Enum


class Route(str, Enum):
    FORM = "form"
    EMAIL = "email"
    IFRAME_ATS = "iframe_ats"
    GATED = "gated"
    NONE = "none"


@dataclass
class FieldObs:
    tag: str                              # "input" | "select" | "textarea"
    type: str = ""                        # email | text | file | checkbox | tel | select | ...
    label: str = ""
    name: str = ""
    required: bool = False
    options: list[str] = field(default_factory=list)   # for select/radio
    ref: str = ""                         # DOM handle set by the scraper (data-af index)


@dataclass
class PageObservation:
    url: str = ""
    fields: list[FieldObs] = field(default_factory=list)
    file_inputs: int = 0
    iframes: list[str] = field(default_factory=list)      # iframe srcs
    mailto_links: list[str] = field(default_factory=list)
    apply_buttons: list[str] = field(default_factory=list)  # visible apply-ish texts
    captcha: bool = False
    login_required: bool = False
    text_excerpt: str = ""
```

- [ ] **Step 2: Write the failing classifier test (with the 3 real-site fixtures)**

Create `sender/tests/test_classify_apply.py`:
```python
from app.application.classify_apply import classify
from app.domain.page_observation import FieldObs, PageObservation, Route


def _f(tag, **kw):
    return FieldObs(tag=tag, **kw)


def test_join_com_gated_by_captcha():
    # Recon 2026-07-14: /apply/authentication had email + reCAPTCHA + "Continue with Google".
    obs = PageObservation(url="https://join.com/.../apply/authentication",
                          fields=[_f("input", type="email", label="Email")],
                          captcha=True)
    assert classify(obs) is Route.GATED


def test_ddrive_mailto_is_email():
    # Recon: no form, "Apply" = mailto:hr@ddrive.tech.
    obs = PageObservation(url="https://www.ddrive.tech/team/junior-software-developer",
                          mailto_links=["mailto:hr@ddrive.tech?subject=Junior"],
                          apply_buttons=["Join the team", "Apply"])
    assert classify(obs) is Route.EMAIL


def test_superplay_cookie_checkboxes_plus_comeet_iframe_is_iframe_ats():
    # Recon: visible fields were only cookie/consent checkboxes; real form in Comeet iframe.
    obs = PageObservation(
        url="https://www.superplay.co/careers-position/26.D66/",
        fields=[_f("input", type="checkbox", label="Performance Cookies"),
                _f("input", type="checkbox", label="checkbox label"),
                _f("input", type="text", label="Cookie list search")],
        iframes=["https://www.comeet.co/jobs/28.003/26.D66/apply?token=x&embedded=true"])
    assert classify(obs) is Route.IFRAME_ATS


def test_greenhouse_like_form():
    obs = PageObservation(
        url="https://boards.greenhouse.io/acme/jobs/1",
        fields=[_f("input", type="email", label="Email", required=True),
                _f("input", type="text", label="First Name", required=True)],
        file_inputs=1)
    assert classify(obs) is Route.FORM


def test_empty_page_is_none():
    assert classify(PageObservation(url="https://x.test")) is Route.NONE
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_classify_apply.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.application.classify_apply'`

- [ ] **Step 4: Implement the classifier**

Create `sender/app/application/classify_apply.py`:
```python
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
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_classify_apply.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: Commit**

```bash
git add sender/app/domain/page_observation.py sender/app/application/classify_apply.py sender/tests/test_classify_apply.py
git commit -m "feat(external-apply): PageObservation types + page classifier"
```

---

### Task 3: Deterministic field mapper + plan

**Files:**
- Create: `sender/app/application/auto_apply.py`
- Test: `sender/tests/test_auto_apply.py`

**Interfaces:**
- Consumes: `FieldObs`, `PageObservation` (Task 2); `ApplyProfile` (Task 1); `is_real_field` (Task 2).
- Produces: `EEO_ANSWER: str`; `FillAction(field, value, choice_index, is_file, needs_ai, source)`; `ApplyPlan(actions)` with `.ai_fields`, `.unmapped_required() -> list[str]`, `.ready_to_submit() -> bool`; `is_fillable_field(f) -> bool`; `map_field(f, profile, cv_path) -> FillAction`; `build_plan(obs, profile, cv_path) -> ApplyPlan`.

- [ ] **Step 1: Write the failing mapper tests**

Create `sender/tests/test_auto_apply.py`:
```python
from app.application.auto_apply import (
    EEO_ANSWER, build_plan, map_field,
)
from app.domain.apply_profile import ApplyProfile
from app.domain.page_observation import FieldObs, PageObservation

PROF = ApplyProfile(
    full_name="Bolatbek Yermekov", first_name="Bolatbek", last_name="Yermekov",
    email="a@b.com", phone="+7 775 720 0604", city="Astana", country="Kazakhstan",
    linkedin="https://linkedin.com/in/x", github="https://github.com/x",
    needs_visa_sponsorship=False, open_to_relocation=True,
    desired_salary="$70,000/year", notice_period="2 weeks",
    custom_answers={"years of experience": "3", "why do you want": ""},
)
CV = "C:/cv.pdf"


def _m(label, tag="input", type="text", **kw):
    return map_field(FieldObs(tag=tag, type=type, label=label, **kw), PROF, CV)


def test_email_phone_name_links_mapped_from_profile():
    assert _m("Email", type="email").value == "a@b.com"
    assert _m("Phone", type="tel").value == "+7 775 720 0604"
    assert _m("First Name").value == "Bolatbek"
    assert _m("LinkedIn URL").value == "https://linkedin.com/in/x"


def test_file_input_gets_cv():
    a = _m("Resume", type="file")
    assert a.is_file and a.value == CV and a.source == "cv"


def test_eeo_field_prefers_not_to_say():
    a = map_field(FieldObs(tag="select", type="select", label="Gender",
                           options=["Male", "Female", "Prefer not to say"]), PROF, CV)
    assert a.choice_index == 2 and a.value == "Prefer not to say"
    a2 = _m("Gender identity")
    assert a2.value == EEO_ANSWER


def test_sponsorship_and_relocation_yes_no():
    spon = map_field(FieldObs(tag="select", type="select",
                              label="Do you require visa sponsorship?",
                              options=["Yes", "No"]), PROF, CV)
    assert spon.choice_index == 1  # No — profile.needs_visa_sponsorship is False
    reloc = map_field(FieldObs(tag="select", type="select", label="Open to relocation?",
                               options=["Yes", "No"]), PROF, CV)
    assert reloc.choice_index == 0  # Yes


def test_custom_answer_match_and_empty_falls_through_to_ai():
    assert _m("Years of experience").value == "3"
    why = _m("Why do you want to work here?", tag="textarea")
    assert why.needs_ai and why.value == ""


def test_free_text_without_profile_match_goes_to_ai():
    a = _m("Describe a challenging project", tag="textarea")
    assert a.needs_ai


def test_readiness_and_unmapped_required():
    obs = PageObservation(fields=[
        FieldObs(tag="input", type="email", label="Email", required=True),
        FieldObs(tag="input", type="text", label="Unknown mandatory code", required=True),
    ])
    plan = build_plan(obs, PROF, CV)
    assert "Unknown mandatory code" in plan.unmapped_required()
    assert plan.ready_to_submit() is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_auto_apply.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.application.auto_apply'`

- [ ] **Step 3: Implement the mapper and plan**

Create `sender/app/application/auto_apply.py`:
```python
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
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_auto_apply.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add sender/app/application/auto_apply.py sender/tests/test_auto_apply.py
git commit -m "feat(external-apply): deterministic field mapper + apply plan"
```

---

### Task 4: AI answering for free-text fields

**Files:**
- Modify: `sender/app/application/auto_apply.py`
- Test: `sender/tests/test_auto_apply.py`

**Interfaces:**
- Consumes: `ApplyPlan`, `FillAction` (Task 3); `app.application.hh_questions.fill_plan` (existing); answerer contract (Global Constraints).
- Produces: `answer_ai_fields(plan: ApplyPlan, answerer, vacancy_context: str) -> None` (mutates the plan's AI actions in place).

- [ ] **Step 1: Write the failing AI-answering test**

Append to `sender/tests/test_auto_apply.py`:
```python
from app.application.auto_apply import answer_ai_fields


def test_answer_ai_fields_fills_text_and_choice_and_readiness():
    obs = PageObservation(fields=[
        FieldObs(tag="textarea", type="text", label="Why do you want to work here?",
                 required=True),
        FieldObs(tag="select", type="select", label="Preferred team",
                 options=["Backend", "Frontend"], required=True),
    ])
    plan = build_plan(obs, PROF, CV)
    assert plan.ready_to_submit() is False        # AI fields empty pre-answering

    def answerer(questions, vacancy_context):
        assert vacancy_context == "JOB TEXT"
        out = {}
        for q in questions:
            if q["type"] == "text":
                out[q["id"]] = {"text": "Because I build AI agents daily."}
            else:
                out[q["id"]] = {"choice": 0}
        return out

    answer_ai_fields(plan, answerer, "JOB TEXT")
    vals = [a.value for a in plan.actions]
    assert "Because I build AI agents daily." in vals
    assert plan.actions[1].choice_index == 0 and plan.actions[1].value == "Backend"
    assert plan.ready_to_submit() is True


def test_answer_ai_fields_noop_without_answerer():
    obs = PageObservation(fields=[FieldObs(tag="textarea", label="Why", required=False)])
    plan = build_plan(obs, PROF, CV)
    answer_ai_fields(plan, None, "ctx")           # must not raise
    assert plan.ai_fields[0].value == ""
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_auto_apply.py -k answer_ai -v`
Expected: FAIL — `ImportError: cannot import name 'answer_ai_fields'`

- [ ] **Step 3: Implement `answer_ai_fields` (reusing hh_questions.fill_plan)**

Append to `sender/app/application/auto_apply.py`:
```python
def answer_ai_fields(plan: ApplyPlan, answerer, vacancy_context: str) -> None:
    """Fill needs_ai actions using the injected answerer. Reuses hh_questions.fill_plan
    to clamp choices and normalise text, keeping one answer format across channels."""
    from app.application.hh_questions import fill_plan

    ai_actions = plan.ai_fields
    if not ai_actions or answerer is None:
        return
    questions = [{
        "id": str(i),
        "type": "choice" if a.field.options else "text",
        "prompt": a.field.label or a.field.name,
        "options": a.field.options,
    } for i, a in enumerate(ai_actions)]

    answers = answerer(questions, vacancy_context) or {}
    tuples = fill_plan(questions, answers)          # [(kind, id, value_or_index), ...]
    by_id = {t[1]: t for t in tuples}
    for i, a in enumerate(ai_actions):
        t = by_id.get(str(i))
        if not t:
            continue
        kind, _, val = t
        if kind == "text":
            a.value = str(val)
        else:
            a.choice_index = int(val)
            if a.field.options and 0 <= a.choice_index < len(a.field.options):
                a.value = a.field.options[a.choice_index]
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_auto_apply.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add sender/app/application/auto_apply.py sender/tests/test_auto_apply.py
git commit -m "feat(external-apply): AI answering for free-text form fields"
```

---

### Task 5: Error type + status wiring (`ManualApplyRequired` / `manual`)

**Files:**
- Modify: `sender/app/domain/channel.py`
- Modify: `sender/app/application/send_outreach.py`
- Modify: `sender/app/domain/lead.py`
- Modify: `sender/app/interface/cli.py:145` (add branch after `elif result.invited:` block)
- Test: `sender/tests/test_send_outreach_manual.py`

**Interfaces:**
- Produces: `ManualApplyRequired(ChannelError)`; `SendResult.manual: bool`; `STATUS_MANUAL = "manual"`.
- Consumes: existing `SendResult`, `SendOutreach.execute`, cli send loop.

- [ ] **Step 1: Write the failing test**

Create `sender/tests/test_send_outreach_manual.py`:
```python
from app.application.send_outreach import SendOutreach
from app.domain.channel import ManualApplyRequired, OutreachContent


class _Lead:
    target = "https://job"


class _Chan:
    def send(self, target, content):
        raise ManualApplyRequired("gated: do it by hand")


def test_manual_apply_required_becomes_manual_result():
    res = SendOutreach(_Chan()).execute(_Lead(), OutreachContent(body="x"))
    assert res.ok is False
    assert res.manual is True
    assert "gated" in res.error
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_send_outreach_manual.py -v`
Expected: FAIL — `ImportError: cannot import name 'ManualApplyRequired'`

- [ ] **Step 3: Add the exception**

In `sender/app/domain/channel.py`, after the `InvitePendingError` class (line 17), add:
```python
class ManualApplyRequired(ChannelError):
    """Not a hard failure: the application can't be completed automatically (CAPTCHA,
    login/registration wall, or an unrecognised form). The lead is flagged for a
    manual apply, with the URL, rather than counted as sent or failed."""
```

- [ ] **Step 4: Add the result field + catch**

In `sender/app/application/send_outreach.py`:

Add to the `SendResult` dataclass (after `invited: bool = False`):
```python
    manual: bool = False         # apply couldn't be automated (CAPTCHA/login/unknown form)
```
Update the imports (add `ManualApplyRequired`) and add a catch clause **before** the generic `except Exception` in `execute`:
```python
        except ManualApplyRequired as exc:
            return SendResult(ok=False, error=str(exc), manual=True)
```

- [ ] **Step 5: Add the status constant**

In `sender/app/domain/lead.py`, after `STATUS_INVITED = "invited"` (line 29):
```python
# Apply couldn't be automated (CAPTCHA/login/unknown form) — do it by hand.
STATUS_MANUAL = "manual"
```

- [ ] **Step 6: Handle the branch in the send loop**

In `sender/app/interface/cli.py`: add `STATUS_MANUAL` to the existing `from app.domain.lead import (...)` block, then insert this branch **after** the `elif result.invited:` block ends (after line 155, before `elif result.rate_limited:`):
```python
                elif result.manual:
                    # Couldn't auto-apply (gate/unknown form); leave for a manual apply.
                    repo.mark_status(lead, STATUS_MANUAL, note=result.error)
                    print(f"✋ Нужен ручной отклик [{platform}]: {result.error}")
```

- [ ] **Step 7: Run the test + full suite to verify green**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_send_outreach_manual.py -v`
Expected: PASS (1 passed)
Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests -q`
Expected: all pass (no regressions).

- [ ] **Step 8: Commit**

```bash
git add sender/app/domain/channel.py sender/app/application/send_outreach.py sender/app/domain/lead.py sender/app/interface/cli.py sender/tests/test_send_outreach_manual.py
git commit -m "feat(external-apply): ManualApplyRequired outcome -> manual status"
```

---

### Task 6: Browser driver — scrape, fill/submit, form/gated/none orchestration

**Files:**
- Create: `sender/app/infrastructure/channels/external_apply.py`
- Test: `sender/tests/test_external_apply.py`

**Interfaces:**
- Consumes: `scrape_form` output → `classify` (Task 2), `build_plan`/`answer_ai_fields` (Tasks 3-4), `ManualApplyRequired` (Task 5).
- Produces: `_SCRAPE_JS: str`; `scrape_form(page) -> PageObservation`; `SEL_SUBMIT: str`; `fill_and_submit(page, plan, dry_run) -> None`; `external_apply(page, job_url, content, profile, cv_path, answerer=None, dry_run=False, email_channel=None, subject_maker=None, vacancy_context="") -> None`. (Email/iframe branches are stubbed to raise `ManualApplyRequired` here; Tasks 8-9 implement them.)

- [ ] **Step 1: Write the failing driver tests (fake Playwright page)**

Create `sender/tests/test_external_apply.py`:
```python
import pytest

from app.application.auto_apply import build_plan
from app.domain.apply_profile import ApplyProfile
from app.domain.channel import ManualApplyRequired, OutreachContent
from app.domain.page_observation import FieldObs, PageObservation
from app.infrastructure.channels import external_apply as ea

PROF = ApplyProfile(full_name="B Y", email="a@b.com")


class FakeLocator:
    def __init__(self, page, sel):
        self.page = page
        self.sel = sel
        self.first = self

    def count(self):
        return 1 if self.sel in self.page.present else 0

    def click(self):
        self.page.clicks.append(self.sel)

    def fill(self, v):
        self.page.filled[self.sel] = v

    def set_input_files(self, v):
        self.page.filled[self.sel] = ("file", v)

    def select_option(self, index):
        self.page.filled[self.sel] = ("choice", index)

    def check(self):
        self.page.filled[self.sel] = ("check", True)


class FakePage:
    def __init__(self, obs, present=()):
        self._obs = obs
        self.present = set(present) | {f'[data-af="{f.ref}"]' for f in obs.fields}
        self.clicks = []
        self.filled = {}

    def evaluate(self, js):        # scrape_form calls page.evaluate(_SCRAPE_JS)
        return ea.observation_to_raw(self._obs)

    def locator(self, sel):
        return FakeLocator(self, sel)


def _obs_form():
    return PageObservation(url="https://boards.greenhouse.io/x/jobs/1", fields=[
        FieldObs(tag="input", type="email", label="Email", required=True, ref="0"),
        FieldObs(tag="input", type="file", label="Resume", required=True, ref="1"),
    ])


def test_form_route_fills_and_submits():
    page = FakePage(_obs_form(), present=[ea.SEL_SUBMIT])
    ea.external_apply(page, "https://job", OutreachContent(body="hi"), PROF, "C:/cv.pdf")
    assert page.filled['[data-af="0"]'] == "a@b.com"
    assert page.filled['[data-af="1"]'] == ("file", "C:/cv.pdf")
    assert ea.SEL_SUBMIT in page.clicks


def test_dry_run_fills_but_does_not_submit():
    page = FakePage(_obs_form(), present=[ea.SEL_SUBMIT])
    with pytest.raises(ManualApplyRequired, match="DRY_RUN"):
        ea.external_apply(page, "https://job", OutreachContent(body="hi"), PROF,
                          "C:/cv.pdf", dry_run=True)
    assert ea.SEL_SUBMIT not in page.clicks
    assert page.filled['[data-af="0"]'] == "a@b.com"


def test_gated_page_raises_manual():
    page = FakePage(PageObservation(url="https://join.com/apply/authentication",
                                    captcha=True))
    with pytest.raises(ManualApplyRequired, match="гейт"):
        ea.external_apply(page, "https://job", OutreachContent(body="hi"), PROF, "C:/cv.pdf")


def test_unmapped_required_raises_manual_before_submit():
    obs = PageObservation(url="https://x", fields=[
        FieldObs(tag="input", type="text", label="Mystery required code",
                 required=True, ref="0")])
    page = FakePage(obs, present=[ea.SEL_SUBMIT])
    # "code" -> AI field, but no answerer -> stays empty -> required-unfilled -> manual
    with pytest.raises(ManualApplyRequired, match="обязательные"):
        ea.external_apply(page, "https://job", OutreachContent(body="hi"), PROF, "C:/cv.pdf")
    assert ea.SEL_SUBMIT not in page.clicks
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_external_apply.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.infrastructure.channels.external_apply'`

- [ ] **Step 3: Implement the driver**

Create `sender/app/infrastructure/channels/external_apply.py`:
```python
"""External-apply driver: read a company ATS page, classify it, and (for a plain
form) fill + submit with the AI. Isolates all Playwright; the decision logic lives
in app.application (classify_apply / auto_apply) and is tested without a browser.

Automating third-party ATS violates their ToS and risks bans (accepted by user).
"""
from app.application.auto_apply import answer_ai_fields, build_plan
from app.application.classify_apply import classify
from app.domain.channel import ChannelError, ManualApplyRequired
from app.domain.page_observation import FieldObs, PageObservation, Route

# Broad submit selector, RU + EN, across ATS themes.
SEL_SUBMIT = (
    "button[type=submit], input[type=submit], "
    "button:has-text('Submit application'), button:has-text('Submit'), "
    "button:has-text('Отправить заявку'), button:has-text('Отправить'), "
    "button:has-text('Send application'), button:has-text('Apply')"
)

# Tags each fillable control with data-af=<idx> (a stable fill handle) and returns
# a compact form snapshot. Mirrors the recon extractor used live on 2026-07-14.
_SCRAPE_JS = r"""() => {
  const norm = s => (s||'').replace(/\s+/g,' ').trim().slice(0,80);
  const labelFor = el => {
    if (el.getAttribute('aria-label')) return norm(el.getAttribute('aria-label'));
    if (el.id) { const l = document.querySelector('label[for="'+el.id+'"]'); if (l) return norm(l.textContent); }
    const l2 = el.closest('label'); if (l2) return norm(l2.textContent);
    if (el.placeholder) return norm(el.placeholder);
    return norm(el.name);
  };
  const controls = [...document.querySelectorAll('input,select,textarea')]
    .filter(e => !['hidden','submit','button','reset','image'].includes(e.type));
  const fields = controls.map((e, i) => {
    e.setAttribute('data-af', String(i));
    return {
      tag: e.tagName.toLowerCase(),
      type: (e.type||'').toLowerCase(),
      label: labelFor(e),
      name: e.name||'',
      required: e.required || e.getAttribute('aria-required')==='true',
      options: e.tagName==='SELECT' ? [...e.options].map(o=>norm(o.textContent)) : [],
      ref: String(i),
    };
  });
  const txt = norm(document.body ? document.body.innerText : '');
  const html = document.documentElement.innerHTML;
  return {
    url: location.href,
    fields,
    file_inputs: document.querySelectorAll('input[type=file]').length,
    iframes: [...document.querySelectorAll('iframe')].map(f=>f.src).filter(Boolean).slice(0,8),
    mailto: [...document.querySelectorAll('a[href^="mailto:"]')].map(a=>a.getAttribute('href')).slice(0,4),
    apply_buttons: [...new Set([...document.querySelectorAll('button,a[role=button],a')]
      .map(b=>norm(b.textContent)).filter(t=>/apply|bewerb|отклик|заявк|application|join/i.test(t)))].slice(0,8),
    captcha: /recaptcha|hcaptcha|turnstile/i.test(html),
    login_required: (document.querySelector('input[type=password]')!=null)
      && /sign in|log in|register|create account|войти|регистрац/i.test(txt),
    text_excerpt: txt.slice(0,240),
  };
}"""


def observation_to_raw(obs: PageObservation) -> dict:
    """Inverse of _build_observation — used by tests' fake page.evaluate()."""
    return {
        "url": obs.url,
        "fields": [{"tag": f.tag, "type": f.type, "label": f.label, "name": f.name,
                    "required": f.required, "options": f.options, "ref": f.ref}
                   for f in obs.fields],
        "file_inputs": obs.file_inputs, "iframes": obs.iframes,
        "mailto": obs.mailto_links, "apply_buttons": obs.apply_buttons,
        "captcha": obs.captcha, "login_required": obs.login_required,
        "text_excerpt": obs.text_excerpt,
    }


def _build_observation(raw: dict) -> PageObservation:
    fields = [FieldObs(tag=f.get("tag", ""), type=f.get("type", ""),
                       label=f.get("label", ""), name=f.get("name", ""),
                       required=bool(f.get("required")), options=f.get("options") or [],
                       ref=f.get("ref", "")) for f in raw.get("fields", [])]
    return PageObservation(
        url=raw.get("url", ""), fields=fields, file_inputs=raw.get("file_inputs", 0),
        iframes=raw.get("iframes", []), mailto_links=raw.get("mailto", []),
        apply_buttons=raw.get("apply_buttons", []), captcha=bool(raw.get("captcha")),
        login_required=bool(raw.get("login_required")),
        text_excerpt=raw.get("text_excerpt", ""))


def scrape_form(page) -> PageObservation:
    return _build_observation(page.evaluate(_SCRAPE_JS))


def fill_and_submit(page, plan, dry_run: bool) -> None:
    for a in plan.actions:
        if not a.field.ref:
            continue
        loc = page.locator(f'[data-af="{a.field.ref}"]')
        if loc.count() == 0:
            continue
        if a.is_file and a.value:
            loc.first.set_input_files(a.value)
        elif a.field.tag == "select" and a.choice_index is not None:
            loc.first.select_option(index=a.choice_index)
        elif a.field.type in ("checkbox", "radio"):
            if a.value:
                loc.first.check()
        elif a.value:
            loc.first.fill(a.value)
    if dry_run:
        return
    submit = page.locator(SEL_SUBMIT)
    if submit.count() == 0:
        raise ManualApplyRequired(f"внешняя форма: не нашёл кнопку отправки: {plan_url(plan)}")
    submit.first.click()


def plan_url(plan) -> str:                # small helper for messages
    return plan.actions[0].field.name if plan.actions else ""


def external_apply(page, job_url: str, content, profile, cv_path: str,
                   answerer=None, dry_run: bool = False, email_channel=None,
                   subject_maker=None, vacancy_context: str = "") -> None:
    obs = scrape_form(page)
    route = classify(obs)

    if route is Route.EMAIL:
        _apply_via_email(obs, content, cv_path, email_channel, subject_maker,
                         vacancy_context)
        return
    if route is Route.IFRAME_ATS:
        _enter_ats_iframe(page, obs)
        obs = scrape_form(page)
        route = classify(obs)
    if route is Route.GATED:
        raise ManualApplyRequired(
            f"внешний отклик за гейтом (CAPTCHA/логин), нужен ручной отклик: {obs.url}")
    if route is not Route.FORM:
        raise ManualApplyRequired(
            f"внешняя форма не распознана, нужен ручной отклик: {obs.url}")

    plan = build_plan(obs, profile, cv_path)
    answer_ai_fields(plan, answerer, vacancy_context or content.body)
    missing = plan.unmapped_required()
    if missing:
        raise ManualApplyRequired(
            f"внешняя форма: не заполнены обязательные поля {missing}, "
            f"нужен ручной отклик: {obs.url}")

    fill_and_submit(page, plan, dry_run)
    if dry_run:
        raise ManualApplyRequired(
            f"APPLY_DRY_RUN: форма заполнена, но НЕ отправлена (проверь вручную): {obs.url}")
    _verify_submitted(page, obs.url)


def _verify_submitted(page, url: str) -> None:
    try:
        page.wait_for_timeout(2000)
    except Exception:  # noqa: BLE001 — fake page in tests has no wait_for_timeout
        pass


def _apply_via_email(obs, content, cv_path, email_channel, subject_maker,
                     vacancy_context) -> None:
    raise ManualApplyRequired(  # implemented in Task 8
        f"внешний отклик по email (mailto), реализуется отдельно: {obs.url}")


def _enter_ats_iframe(page, obs) -> None:
    raise ManualApplyRequired(  # implemented in Task 9
        f"внешняя форма во встроенном ATS (iframe), реализуется отдельно: {obs.url}")
```

Note: `fill_and_submit`'s "no submit button" message calls `plan_url`, which is a weak stand-in; keep it — messages are for humans and the URL is already in the caller's raises. (Simplify later if desired.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_external_apply.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add sender/app/infrastructure/channels/external_apply.py sender/tests/test_external_apply.py
git commit -m "feat(external-apply): Playwright driver (scrape/classify/fill/submit + dry-run)"
```

---

### Task 7: LinkedIn hand-off + registry injection + end-to-end wiring (Phase 1 complete)

**Files:**
- Modify: `sender/app/infrastructure/channels/linkedin.py`
- Modify: `sender/app/infrastructure/channels/registry.py`
- Test: `sender/tests/test_linkedin_external.py`

**Interfaces:**
- Consumes: `external_apply` (Task 6); `EXTERNAL_APPLY_ENABLED`/`APPLY_DRY_RUN`/`APPLY_PROFILE_PATH` (Task 1); `load_apply_profile` (Task 1); `_hh_answerer` (existing).
- Produces: `LinkedInChannel.__init__(..., external_apply_deps=None)`; on an external-apply job, `LinkedInChannel.send` invokes `external_apply` instead of raising.

- [ ] **Step 1: Write the failing hand-off test**

Create `sender/tests/test_linkedin_external.py`:
```python
from app.domain.channel import OutreachContent
from app.infrastructure.channels import linkedin as li


class Loc:
    def __init__(self, n):
        self._n = n
        self.first = self

    def count(self):
        return self._n

    def click(self):
        pass


class Page:
    def __init__(self, has_easy_apply):
        self._has = has_easy_apply

    def goto(self, url, wait_until=None):
        pass

    def locator(self, sel):
        # No Easy Apply button => external-apply job.
        return Loc(1 if (self._has and "jobs-apply-button" in sel) else 0)


def test_external_job_calls_external_apply_when_enabled():
    calls = {}

    def fake_external(page, job_url, content, **kw):
        calls["job_url"] = job_url

    ch = li.LinkedInChannel("state.json", headless=True,
                            external_apply_deps={"enabled": True, "fn": fake_external})
    ch._page = Page(has_easy_apply=False)
    ch.send("https://www.linkedin.com/jobs/view/123", OutreachContent(body="hi"))
    assert calls["job_url"] == "https://www.linkedin.com/jobs/view/123"


def test_external_job_raises_when_disabled():
    ch = li.LinkedInChannel("state.json", headless=True,
                            external_apply_deps={"enabled": False, "fn": None})
    ch._page = Page(has_easy_apply=False)
    try:
        ch.send("https://www.linkedin.com/jobs/view/123", OutreachContent(body="hi"))
        assert False, "expected ChannelError"
    except li.ChannelError as exc:
        assert "внешний отклик" in str(exc)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_linkedin_external.py -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'external_apply_deps'`

- [ ] **Step 3: Modify `linkedin.py`**

In `sender/app/infrastructure/channels/linkedin.py`:

(a) Add a module-level selector after `SEL_EASY_APPLY` (line 14):
```python
# External-apply button (no Easy Apply): a link/button that opens the company site.
# Verified selectors drift; this is best-effort RU+EN and may need live tuning.
SEL_EXTERNAL_APPLY = (
    "a.jobs-apply-button, "
    "a:has-text('Подать заявку'), button:has-text('Подать заявку'), "
    "a:has-text('Apply'), button:has-text('Apply')"
)
```

(b) Replace the body of `easy_apply_via_page` (lines 130-150) so the external case raises an internal signal instead of a hard error:
```python
class _ExternalApplyNeeded(Exception):
    """Internal: this LinkedIn job has no Easy Apply; the caller runs external apply."""


def easy_apply_via_page(page, job_url: str, content: OutreachContent) -> None:
    """Open a job and submit via Easy Apply. Raises _ExternalApplyNeeded when the
    job's only route is an external company site (handled by the channel)."""
    page.goto(job_url, wait_until="domcontentloaded")
    apply_btn = page.locator(SEL_EASY_APPLY)
    if apply_btn.count() == 0:
        raise _ExternalApplyNeeded()
    apply_btn.first.click()
    submit = page.locator(SEL_APPLY_SUBMIT)
    if submit.count() == 0:
        raise ChannelError(
            f"LinkedIn Easy Apply многошаговый, нужен ручной отклик: {job_url}")
    submit.first.click()
```

(c) Extend `LinkedInChannel.__init__` to accept `external_apply_deps` (default `None`):
```python
    def __init__(self, storage_state_path: str, headless: bool = False,
                 external_apply_deps=None):
        self._storage_state_path = storage_state_path
        self._headless = headless
        # {"enabled": bool, "fn": callable, plus kwargs profile/cv_path/answerer/
        #  dry_run/email_channel/subject_maker} — built in the registry.
        self._ext = external_apply_deps or {"enabled": False, "fn": None}
        self._pw = None
        self._browser = None
        self._page = None
```

(d) In `LinkedInChannel.send`, wrap the `easy_apply` branch to catch the signal:
```python
        if action == "easy_apply":
            try:
                easy_apply_via_page(self._page, target, content)
            except _ExternalApplyNeeded:
                self._external_apply(target, content)
            return
```

(e) Add the `_external_apply` method to the class (grabbing the LinkedIn job description for AI context, clicking through, handling a possible new tab):
```python
    def _external_apply(self, job_url: str, content: OutreachContent) -> None:
        if not self._ext.get("enabled") or self._ext.get("fn") is None:
            raise ChannelError(
                f"внешний отклик LinkedIn (не Easy Apply), нужен ручной отклик: {job_url}")
        page = self._page
        try:
            desc = page.locator("div.jobs-description, main").first.inner_text(timeout=5000)[:6000]
        except Exception:  # noqa: BLE001
            desc = ""
        apply_page = page
        btn = page.locator(SEL_EXTERNAL_APPLY)
        if btn.count() > 0:
            try:
                with page.context.expect_page(timeout=15000) as popup:
                    btn.first.click()
                apply_page = popup.value
            except Exception:  # noqa: BLE001 — same-tab navigation, no popup
                apply_page = page
        fn = self._ext["fn"]
        fn(apply_page, job_url, content,
           profile=self._ext.get("profile"), cv_path=self._ext.get("cv_path", ""),
           answerer=self._ext.get("answerer"), dry_run=self._ext.get("dry_run", False),
           email_channel=self._ext.get("email_channel"),
           subject_maker=self._ext.get("subject_maker"), vacancy_context=desc)
```

- [ ] **Step 4: Run the hand-off test**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_linkedin_external.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Wire the registry to build and inject the deps**

In `sender/app/infrastructure/channels/registry.py`, replace the `linkedin` branch (line 38-39) with:
```python
    if platform == "linkedin":
        return LinkedInChannel(config.LINKEDIN_STATE_PATH, config.BROWSER_HEADLESS,
                               external_apply_deps=_external_apply_deps(config))
```
And add this builder above `build_channel`:
```python
def _external_apply_deps(config):
    if not getattr(config, "EXTERNAL_APPLY_ENABLED", False):
        return {"enabled": False, "fn": None}
    from app.infrastructure.apply_profile_loader import load_apply_profile
    from app.infrastructure.channels.external_apply import external_apply
    from app.application.generate_message import subject_for
    email_channel = None
    if getattr(config, "SMTP_HOST", "") and getattr(config, "SMTP_USER", ""):
        email_channel = EmailChannel(config.SMTP_HOST, config.SMTP_PORT, config.SMTP_USER,
                                     config.SMTP_PASSWORD, config.EMAIL_FROM_NAME)
    return {
        "enabled": True,
        "fn": external_apply,
        "profile": load_apply_profile(config.APPLY_PROFILE_PATH),
        "cv_path": config.CV_PATH,
        "answerer": _hh_answerer(config),      # generic CV+profile AI answerer
        "dry_run": getattr(config, "APPLY_DRY_RUN", False),
        "email_channel": email_channel,
        "subject_maker": subject_for,
    }
```

- [ ] **Step 6: Run the full suite (no regressions)**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add sender/app/infrastructure/channels/linkedin.py sender/app/infrastructure/channels/registry.py sender/tests/test_linkedin_external.py
git commit -m "feat(external-apply): LinkedIn hand-off + registry injection (Phase 1 e2e)"
```

---

### Task 8: Email route (Phase 2)

**Files:**
- Modify: `sender/app/infrastructure/channels/external_apply.py` (`_apply_via_email`)
- Test: `sender/tests/test_external_apply.py`

**Interfaces:**
- Consumes: `email_channel.send(addr, OutreachContent)` (existing `EmailChannel`); `subject_maker(job_text) -> str` (existing `subject_for`).
- Produces: working `_apply_via_email`; on the email route, sends a real email with CV and returns (no raise).

- [ ] **Step 1: Write the failing email-route test**

Append to `sender/tests/test_external_apply.py`:
```python
def _obs_mailto():
    return PageObservation(url="https://ddrive.tech/team/junior",
                           mailto_links=["mailto:hr@ddrive.tech?subject=Junior%20Dev"],
                           apply_buttons=["Apply"])


class RecordingEmail:
    def __init__(self):
        self.sent = []

    def start(self): pass
    def stop(self): pass

    def send(self, target, content):
        self.sent.append((target, content.subject, content.attachment_path))


def test_email_route_sends_via_email_channel():
    page = FakePage(_obs_mailto())
    mail = RecordingEmail()
    ea.external_apply(page, "https://job", OutreachContent(body="cover letter"),
                      PROF, "C:/cv.pdf", email_channel=mail,
                      subject_maker=lambda ctx: "Application: Junior Dev",
                      vacancy_context="JOB")
    assert mail.sent == [("hr@ddrive.tech", "Application: Junior Dev", "C:/cv.pdf")]


def test_email_route_without_channel_raises_manual():
    page = FakePage(_obs_mailto())
    with pytest.raises(ManualApplyRequired, match="email"):
        ea.external_apply(page, "https://job", OutreachContent(body="x"), PROF, "C:/cv.pdf")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_external_apply.py -k email -v`
Expected: FAIL — first test fails (current stub raises `ManualApplyRequired`).

- [ ] **Step 3: Implement `_apply_via_email`**

In `sender/app/infrastructure/channels/external_apply.py`, add an import at the top:
```python
from urllib.parse import unquote, urlsplit

from app.domain.channel import OutreachContent
```
Replace the stub `_apply_via_email` body with:
```python
def _apply_via_email(obs, content, cv_path, email_channel, subject_maker,
                     vacancy_context) -> None:
    if email_channel is None:
        raise ManualApplyRequired(
            f"внешний отклик по email, но email-канал не настроен (SMTP): {obs.url}")
    addr = _mailto_address(obs.mailto_links[0])
    if not addr:
        raise ManualApplyRequired(f"внешний отклик по email: не разобрал адрес: {obs.url}")
    subject = (subject_maker(vacancy_context) if subject_maker else "Application").strip()
    email_channel.send(addr, OutreachContent(
        subject=subject or "Application", body=content.body, attachment_path=cv_path))


def _mailto_address(mailto: str) -> str:
    # "mailto:hr@x.com?subject=..." -> "hr@x.com"
    rest = mailto[len("mailto:"):] if mailto.lower().startswith("mailto:") else mailto
    addr = urlsplit(rest).path or rest.split("?", 1)[0]
    return unquote(addr).strip()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_external_apply.py -v`
Expected: PASS (all external-apply tests, incl. the 2 new email ones).

- [ ] **Step 5: Commit**

```bash
git add sender/app/infrastructure/channels/external_apply.py sender/tests/test_external_apply.py
git commit -m "feat(external-apply): email route (mailto -> email channel)"
```

---

### Task 9: iframe ATS route (Phase 3)

**Files:**
- Modify: `sender/app/infrastructure/channels/external_apply.py` (`_enter_ats_iframe` + reveal-click)
- Test: `sender/tests/test_external_apply.py`

**Interfaces:**
- Consumes: `known_ats_iframe` (Task 2), `page.goto` (Playwright).
- Produces: working `_enter_ats_iframe(page, obs)` that navigates the page to the embedded ATS form's own URL, so a re-scrape sees a plain FORM.

- [ ] **Step 1: Write the failing iframe-route test**

Append to `sender/tests/test_external_apply.py`:
```python
class NavFakePage(FakePage):
    """Fake page whose observation changes after goto() (iframe src -> real form)."""
    def __init__(self, first_obs, after_goto_obs):
        super().__init__(first_obs)
        self._after = after_goto_obs
        self.goto_url = None

    def goto(self, url, wait_until=None):
        self.goto_url = url
        self._obs = self._after
        self.present |= {f'[data-af="{f.ref}"]' for f in self._after.fields}


def test_iframe_ats_navigates_into_frame_then_fills():
    comeet = "https://www.comeet.co/jobs/28/26/apply?token=x&embedded=true"
    first = PageObservation(url="https://superplay.co/careers/1", iframes=[comeet],
                            fields=[FieldObs(tag="input", type="checkbox",
                                             label="Functional Cookies", ref="0")])
    inner = PageObservation(url=comeet, fields=[
        FieldObs(tag="input", type="email", label="Email", required=True, ref="0")],
        file_inputs=1)
    page = NavFakePage(first, inner)
    page.present.add(ea.SEL_SUBMIT)
    ea.external_apply(page, "https://job", OutreachContent(body="hi"), PROF, "C:/cv.pdf")
    assert page.goto_url == comeet
    assert page.filled['[data-af="0"]'] == "a@b.com"
    assert ea.SEL_SUBMIT in page.clicks
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_external_apply.py -k iframe -v`
Expected: FAIL — current stub `_enter_ats_iframe` raises `ManualApplyRequired`.

- [ ] **Step 3: Implement `_enter_ats_iframe`**

In `sender/app/infrastructure/channels/external_apply.py`, add the import:
```python
from app.application.classify_apply import known_ats_iframe
```
Replace the stub `_enter_ats_iframe` with:
```python
def _enter_ats_iframe(page, obs) -> None:
    """The application form is embedded from a known ATS (e.g. Comeet). Navigate the
    page directly to the iframe's own URL so a re-scrape sees a plain form. The src
    already carries the position token, so the form loads standalone."""
    src = known_ats_iframe(obs.iframes)
    if not src:
        raise ManualApplyRequired(f"встроенный ATS не распознан: {obs.url}")
    page.goto(src, wait_until="domcontentloaded")
```
(Note: `wait_until` is accepted by the real Playwright `goto`; the test's `goto` ignores it.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_external_apply.py -v`
Expected: PASS (all external-apply tests).

- [ ] **Step 5: Commit**

```bash
git add sender/app/infrastructure/channels/external_apply.py sender/tests/test_external_apply.py
git commit -m "feat(external-apply): iframe ATS route (navigate into embedded form)"
```

---

### Task 10: Live test on the three real URLs + Makefile target (Phase 3)

**Files:**
- Create: `sender/pytest.ini`
- Create: `sender/tests/test_apply_live.py`
- Modify: `Makefile`
- Modify: `sender/requirements.txt` (add `pytest` if not present) — verify first.

**Interfaces:**
- Consumes: `scrape_form`, `classify`, `build_plan` (Tasks 2-6); Playwright chromium.
- Produces: opt-in live test asserting the recon routing for the 3 URLs; `make apply_probe`; `make test-unit` excludes live tests.

- [ ] **Step 1: Register the `live` marker so it never runs in the normal suite**

Create `sender/pytest.ini`:
```ini
[pytest]
markers =
    live: hits real external sites over the network; opt-in only (run with -m live).
addopts = -m "not live"
```
(Existing `make test-unit` runs `pytest sender/tests`; `addopts` makes it skip live by default.)

- [ ] **Step 2: Write the live test (classification/DRY-RUN only — submits nothing)**

Create `sender/tests/test_apply_live.py`:
```python
"""Live routing check on three real external-apply URLs (recon 2026-07-14).

SAFETY: read-only. Navigates, scrapes, and classifies each page; it NEVER clicks
Submit, so no application is sent to Lemvos / DataDrive / SuperPlay. Opt-in and
excluded from the normal suite (pytest.ini addopts = -m "not live").

Run: make apply_probe
Flaky by nature (network, anti-bot, sites change). Replace URLs if they 404.
"""
import pytest

from app.application.classify_apply import classify
from app.domain.page_observation import Route
from app.infrastructure.channels.external_apply import scrape_form

pytestmark = pytest.mark.live

CASES = [
    ("https://join.com/companies/lemvos/16426802-mandatory-internship-web-development"
     "?pid=e65242534431eadcb0c9", Route.GATED, "click"),   # gate revealed after "Apply now"
    ("https://www.ddrive.tech/team/junior-software-developer", Route.EMAIL, "direct"),
    ("https://www.superplay.co/careers-position/26.D66/?coref=1.11.pF3_BB1B",
     Route.IFRAME_ATS, "direct"),
]


@pytest.fixture(scope="module")
def page():
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    pg = browser.new_context().new_page()
    yield pg
    browser.close()
    pw.stop()


@pytest.mark.parametrize("url,expected,mode", CASES, ids=lambda v: str(v)[:30])
def test_real_url_routes_as_expected(page, url, expected, mode):
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    if mode == "click":
        # join.com: the gate appears only after clicking "Apply now".
        btn = page.locator("button[data-testid='ApplyButton'], button:has-text('Apply now')")
        if btn.count():
            btn.first.click()
            page.wait_for_timeout(3000)
    obs = scrape_form(page)
    route = classify(obs)
    assert route is expected, f"{url} -> {route} (fields={len(obs.fields)}, iframes={obs.iframes[:1]})"
```

- [ ] **Step 3: Add the Makefile target and exclude live from the unit run**

In `Makefile`: add `apply_probe` to the `.PHONY` line, then append a target:
```make
apply_probe:
	$(PYTHON) -m pytest sender/tests/test_apply_live.py -v -m live
```
And change the `test-unit` target so the network tests never run by accident:
```make
test-unit:
	$(PYTHON) -m pytest sender/tests -v -m "not live"
```
Also add a comment line near the top help block:
```
#   make apply_probe    -> LIVE routing check on the 3 real external-apply URLs (network; no submit)
```

- [ ] **Step 4: Verify the normal suite still green and excludes live**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests -v`
Expected: PASS; `test_apply_live.py` shows as deselected (by `-m "not live"`).

- [ ] **Step 5: Run the live probe (network required)**

Run: `sender/.venv/Scripts/python.exe -m pytest sender/tests/test_apply_live.py -v -m live`
Expected: 3 passed — `join.com -> GATED`, `ddrive -> EMAIL`, `superplay -> IFRAME_ATS`.
If a site changed and a case fails, inspect the printed `fields`/`iframes` and adjust the classifier or the URL; do not weaken the safety (never submit).

- [ ] **Step 6: Commit**

```bash
git add sender/pytest.ini sender/tests/test_apply_live.py Makefile
git commit -m "test(external-apply): live routing probe on 3 real URLs + make apply_probe"
```

---

## Self-Review

**Spec coverage:**
- §2 recon cases → Task 2 fixtures + Task 10 live test (join=gated, ddrive=email, superplay=iframe_ats). ✅
- §3 decisions: universal filler+router (Tasks 2-6); full-auto+guardrails (Task 6 dry-run, unmapped-required, gated skip); structured profile+skip-empty (Tasks 1,3). ✅
- §5 architecture files → Tasks 1-2-3-6-7 create exactly those modules; layering preserved. ✅
- §6 classifier (cookie filter, apply-form heuristic, known ATS, mailto) → Task 2. ✅
- §7 data flow (click→classify→branch→plan→ready?→fill/submit) → Tasks 6-7. ✅
- §8 apply_profile.yml schema → Task 1 `ApplyProfile` + loader (file already created). ✅
- §9 guardrails → Task 6 (dry-run, required-check, gated, verify), Task 5 (manual status). ✅
- §10 errors/status (`ManualApplyRequired`, `SendResult.manual`, `manual` status) → Task 5. ✅
- §11 config → Task 1. ✅
- §12 reuse (hh_questions.fill_plan, answer_questions, email_channel, cv_loader, subject_for, _hh_answerer) → Tasks 4,7,8. ✅
- §13 tests: offline units (Tasks 1-9) + opt-in live 3-URL (Task 10, DRY/classification only). ✅
- §14 phases: Phase 1 (Tasks 1-7), Phase 2 (Task 8), Phase 3 (Tasks 9-10). Phase 4 out of scope (noted). ✅

**Placeholder scan:** No TBD/TODO; every code step has complete code; the two stubs in Task 6 (`_apply_via_email`, `_enter_ats_iframe`) intentionally raise `ManualApplyRequired` and are replaced with real code in Tasks 8-9 (not placeholders — they are correct fail-safe behaviour if those phases are skipped). ✅

**Type consistency:** `FieldObs`/`PageObservation`/`Route` defined in Task 2 and used with the same names/fields throughout; `FillAction`/`ApplyPlan` from Task 3 used consistently in Tasks 4,6; answerer contract identical to `_hh_answerer` and `fill_plan`; `external_apply(...)` signature identical in Task 6 (definition), Task 7 (call via `fn(...)`), Tasks 8-9 (branch impls). `observation_to_raw`/`_build_observation` are inverses and cover the fake-page path. ✅

**Known fragile point (flagged, not a gap):** `SEL_EXTERNAL_APPLY` (Task 7) is the one selector not verified live against a LinkedIn external-apply job page; it is best-effort and may need tuning during the first real run. All other selectors/flows are grounded in the 2026-07-14 recon or existing code.
