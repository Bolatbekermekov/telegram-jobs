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
