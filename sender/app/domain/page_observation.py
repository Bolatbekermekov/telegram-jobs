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
    # Сколько знаков поле готово принять; 0 — не объявлено. Не всегда атрибут:
    # LinkedIn держит предел только в подсказке («Использовано: 37 из 20
    # символов»), а превышение отзывается «Недопустимым значением» без единого
    # `role=alert`. Ответ, который в поле не влезает, не отвергается на месте —
    # он молча не даёт экрану смениться.
    max_len: int = 0
    ref: str = ""                         # DOM handle set by the scraper (data-af index)
    # Полный текст вопроса — для модели. `label` режется до 80 знаков, и по его
    # длине правила отличают подпись от абзаца; вопрос-абзац при этом доходил до
    # модели обрубком (живьём 2026-09-13, Workable, лид #1164: «…4) Prefe»).
    question: str = ""
    # Что принимает файловое поле — его `accept`, как объявила страница; пусто —
    # что угодно. Живьём 2026-09-13 (Workable, лид #1164) резюме уехало в «Photo»:
    # подпись у поля была мусорная, а `accept` честно говорил «только картинки».
    accept: str = ""
    # Границы шкалы `input type=range`, как их объявила страница; у прочих полей
    # пусто. Живьём 2026-09-14 (лид #1237, Teamtailor): «rate yourself in Python»
    # от 1 до 5 — без границ модель отвечала по своей мерке.
    range_min: str = ""
    range_max: str = ""
    range_step: str = ""
    # Подсказка формата, как её объявила страница: placeholder («DD/MM/YYYY»),
    # язык поля и календарь рядом. Живьём 2026-09-14 (лид #1216, LinkedIn Easy
    # Apply): «Date Of Birth *» — вход календаря с lang="en-US" без placeholder,
    # и порядок дня и месяца виден только по языку.
    placeholder: str = ""
    lang: str = ""
    date_picker: bool = False


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
