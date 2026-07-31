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

    def is_blank(self) -> bool:
        """True when nothing identifying was filled in.

        `load_apply_profile` returns an all-empty profile when the YAML file is
        absent, and that is indistinguishable at the call site from a file someone
        wrote and left empty. Either way no external form can be filled: every
        required field comes back unmapped and the lead parks as `manual`, having
        already cost one OpenAI generation and one browser round-trip — every run,
        forever, because nothing about it changes. Worth saying out loud once at
        startup instead of thirty times in the notes column.
        """
        return not (self.full_name.strip() or self.first_name.strip()
                    or self.email.strip())
