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
