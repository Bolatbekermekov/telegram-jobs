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

# Longest a label can be and still be treated as a field caption. Beyond this it
# reads as a question (or as prose smuggling keywords), so keyword rules stop
# applying — see map_field. "Are you legally authorized to work in the US?" is 46.
_MAX_LABEL_CHARS = 80

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


# A select's "nothing chosen yet" option. Its text is what the scraper reports as
# the field's current value, so without this list an untouched dropdown would read
# as already answered.
_PLACEHOLDER_OPTION_RE = re.compile(
    r"^(select(\s+an?\s+\w+)?|please select|choose(\s+\w+)?|"
    r"выбер(и|ите)[^|]*|выбрать|не выбрано|[-—–])\.{0,3}$", re.IGNORECASE)


def _satisfied(a: FillAction) -> bool:
    if a.is_file:
        return bool(a.value)
    if a.choice_index is not None:
        return True
    if a.value.strip() and "[" not in a.value:
        return True
    # Nothing planned for it, but the page already carries an answer. Measured on
    # LinkedIn Easy Apply (2026-07-29): the form arrives with the account's email
    # and «Phone country code» already selected, and neither can be matched from
    # the profile — the account email need not be the profile one, and a code like
    # "Kazakhstan (+7)" is not a phone number. Treating those as unfilled is what
    # made every Easy Apply job unreachable.
    current = a.field.value.strip()
    return bool(current) and not _PLACEHOLDER_OPTION_RE.match(current)


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
    # Length is judged on the LABEL alone, never on label+name. Ashby names every
    # field with a UUID ("8d640ab2-9852-452b-9798-92d28cba…"), which adds ~37
    # characters of noise — enough to push any real question past the caption
    # limit and switch off every keyword rule for it. That is what kept the
    # salary question unanswered on lead 123 after the model was already
    # answering it correctly in isolation (measured 2026-07-29).
    caption_len = len((f.label or "").strip() or low)

    if f.type == "file":
        # Attach the CV only to a resume/CV upload — never to a cover-letter,
        # portfolio, photo, or other document field we don't have a file for.
        if re.search(r"cover|portfolio|photo|picture|certificate|transcript|other", low):
            return FillAction(field=f, source="unmapped")
        return FillAction(field=f, value=cv_path, is_file=True, source="cv")

    # Personal-status questions belong here too: "Marital Status" is the same kind
    # of question as gender, and "I prefer not to say" is on the form for exactly
    # this reason. Better that than a model guessing at someone's private life.
    if re.search(r"gender|race|ethnic|veteran|disabilit|sexual orientation|pronoun|"
                 r"marital|family status|семейное положение|пол\b", low):
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

    # Whole-word match, not substring: the label comes from a third-party page, so
    # a key like "salary" used as a substring would also fire on "your friend's
    # salary" or "salary of your last manager" and hand over a prepared answer.
    label_words = set(re.findall(r"[a-zа-яё0-9]+", low))
    for key, ans in profile.custom_answers.items():
        key = (key or "").strip().lower()
        if not key:
            continue
        key_words = re.findall(r"[a-zа-яё0-9]+", key)
        if not key_words:
            continue
        if len(key_words) == 1:
            matched = key_words[0] in label_words
        else:                       # multi-word key: match the phrase in order
            matched = re.search(r"\b" + r"\W+".join(map(re.escape, key_words)) + r"\b", low)
        if matched:
            if ans:
                return FillAction(field=f, value=ans, source="custom")
            return FillAction(field=f, needs_ai=True, source="ai")

    # Salary is the one recognised field whose right answer depends on the JOB, not
    # on a number we carry around: "minimum you would accept, in £ per month" has a
    # different answer for a London fintech and a remote contract. A fixed
    # `desired_salary` still wins when it is set; otherwise the model answers it
    # with the vacancy in front of it. Handled before the caption rules because
    # those would return "recognised but empty" and leave a REQUIRED salary box
    # blank, which parks the whole application.
    # Caption-length only, like every other keyword rule: "Describe a project where
    # you justified the salary budget of your team" is prose, and handing it a
    # stored figure instead of an answer is exactly what _MAX_LABEL_CHARS exists
    # to prevent. Longer labels fall through to the free-text branch below, which
    # sends them to the model anyway.
    if (caption_len <= _MAX_LABEL_CHARS
            and re.search(r"salary|compensation|expected pay|\brate\b|зарплат|оклад", low)):
        if profile.desired_salary:
            return FillAction(field=f, value=profile.desired_salary, source="profile")
        return FillAction(field=f, needs_ai=True, source="ai")

    # _LABEL_RULES match anywhere in the label, which is right for a real caption
    # ("Email", "Your phone number") but wrong for prose: a question ending in
    # "…и укажи email кандидата" would otherwise hand over the address without the
    # model ever being asked. Real captions are short, so prose skips these rules
    # and falls through to the free-text branch below.
    if caption_len <= _MAX_LABEL_CHARS:
        for rx, resolver in _LABEL_RULES:
            if rx.search(low):
                val = resolver(profile)
                if not val:
                    # Recognised field (linkedin/website/salary/…) but no profile
                    # value: leave it empty rather than dumping AI prose into it.
                    return FillAction(field=f, source="unmapped")
                if f.options:
                    # A dropdown takes an option, not typed text — .fill() on a
                    # <select> raises, and that raise on a REQUIRED field is a
                    # manual apply. LinkedIn serves email as a select of the
                    # account's verified addresses.
                    idx = _option_index_for(f.options, val)
                    if idx is None:
                        return FillAction(field=f, source="unmapped")
                    return FillAction(field=f, choice_index=idx,
                                      value=f.options[idx], source="profile")
                return FillAction(field=f, value=val, source="profile")

    # Free text only: a textarea, or an input whose label reads like an open question.
    if f.tag == "textarea" or re.search(
            r"why|cover letter|message|motivat|tell us|describe|\bnote\b|question|"
            r"about you|about yourself|yourself", low):
        return FillAction(field=f, needs_ai=True, source="ai")
    # An unrecognised dropdown gets an AI answer ONLY when the form requires one.
    # Optional ones are left strictly alone: not every <select> on a page belongs
    # to the application. LinkedIn's Easy Apply renders its interface-language
    # picker inside the contact step, and this rule answered it — the model took
    # the first option and switched the whole account to Arabic (observed
    # 2026-07-29, ar_AE, restored by hand). Every text-based selector then stopped
    # matching, so the flow could not be driven either. A required dropdown we
    # must answer is a fair thing to guess at; an optional one is somebody else's
    # setting, and the cost of touching it is unbounded.
    # A RADIO group is a question by construction — several labelled answers to
    # one prompt, inside an application form — so it gets answered whether or not
    # the DOM bothered to mark it required. Ashby marks none of them, and the form
    # then refuses the submit for a field nothing had flagged.
    #
    # A `select` still needs the required flag. That is the control the language
    # picker turned out to be, and answering optional ones cost the account its
    # interface language; the distinction is what keeps both lessons.
    if f.options and (f.required or f.type == "radio"):
        return FillAction(field=f, needs_ai=True, source="ai")

    # A plain short input we don't recognise: leave it empty rather than AI-filling
    # prose into a name/url/id-type box. If required, the plan flags it -> manual.
    return FillAction(field=f, source="unmapped")


def _option_index_for(options: list[str], value: str) -> int | None:
    """Index of the option carrying `value`, or None when none does.

    Exact match first, then containment either way — an option may read
    "Kazakhstan (+7)" for a value of "+7", or "ivan@x.com" for "Ivan@X.com".
    """
    v = (value or "").strip().lower()
    if not v:
        return None
    opts = [(o or "").strip().lower() for o in options]
    for i, o in enumerate(opts):
        if o == v:
            return i
    for i, o in enumerate(opts):
        if o and (v in o or o in v) and not _PLACEHOLDER_OPTION_RE.match(o):
            return i
    return None


_COUNTRY_CODE_LABEL_RE = re.compile(r"country code|код страны", re.IGNORECASE)
_PHONE_LABEL_RE = re.compile(r"phone|mobile|телефон", re.IGNORECASE)
_LEADING_COUNTRY_CODE_RE = re.compile(r"^\+\d{1,3}[\s\-()]*")


def _drop_duplicated_country_code(actions: list[FillAction]) -> None:
    """Strip the country code from a phone value when the form asks for it apart.

    LinkedIn's Easy Apply carries a «Phone country code» select (already set to
    "Kazakhstan (+7)") beside an empty «Mobile phone number». The profile holds
    one full number, "+7 775 720 0604", so typing it into the second control
    submits the code twice. Workday and Greenhouse split the same way.
    """
    if not any(_COUNTRY_CODE_LABEL_RE.search(f"{a.field.label} {a.field.name}")
               for a in actions):
        return
    for a in actions:
        if a.choice_index is not None or not a.value:
            continue
        low = f"{a.field.label} {a.field.name}"
        if _PHONE_LABEL_RE.search(low) and not _COUNTRY_CODE_LABEL_RE.search(low):
            a.value = _LEADING_COUNTRY_CODE_RE.sub("", a.value).strip()


_RESUME_LABEL_RE = re.compile(r"resume|\bcv\b|резюме", re.IGNORECASE)


def _only_the_real_resume_field(actions: list[FillAction]) -> None:
    """When a form has several file inputs, upload only to the one asking for a CV.

    Ashby puts an unlabelled "Autofill from resume" dropzone above its actual
    application form. Uploading there is not part of applying — it makes the
    server REBUILD the form (`ApiAutofillApplicationFormWithUploadedResume`
    returns a new render id), so every value set around it belongs to a form that
    no longer exists, and the Submit that follows fires no request at all
    (measured on lead 123, 2026-07-29: 22 setFormValue calls, zero submits).

    An unlabelled file input is only used when nothing on the form names a resume.
    """
    files = [a for a in actions if a.is_file]
    if len(files) < 2:
        return
    named = [a for a in files
             if _RESUME_LABEL_RE.search(f"{a.field.label} {a.field.name}")]
    if not named:
        return
    for a in files:
        if a not in named:
            a.is_file, a.value, a.source = False, "", "unmapped"


def build_plan(obs: PageObservation, profile: ApplyProfile, cv_path: str) -> ApplyPlan:
    actions = [map_field(f, profile, cv_path)
               for f in obs.fields if is_fillable_field(f)]
    _drop_duplicated_country_code(actions)
    _only_the_real_resume_field(actions)
    return ApplyPlan(actions=actions)


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
        # Say when the box only takes digits. Without it the model answers a
        # salary question with "£5000", which <input type=number> rejects
        # outright — the value is salvaged on the way in either way, but an
        # answer that fits the box is better than one that has to be repaired.
        "prompt": ((a.field.label or a.field.name) +
                   (" (ответ: ТОЛЬКО число, без валюты, символов и слов)"
                    if a.field.type == "number" else "")),
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
