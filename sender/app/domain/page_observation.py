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
    # What the control already holds when scraped (a select reports the chosen
    # option's TEXT, so it can be compared against `options`). Empty for a blank
    # field. Some forms arrive prefilled — LinkedIn's Easy Apply comes with the
    # account's email and phone country code already chosen — and a required
    # field that is already correct must not read as one we failed to fill.
    value: str = ""
    # True for a typeahead: an input that looks like free text but only accepts a
    # value chosen from its own suggestion list. LinkedIn's «Location (city)» is
    # one — typed text is rejected with "Please enter a valid answer".
    combobox: bool = False
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
