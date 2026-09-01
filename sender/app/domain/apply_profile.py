"""Canonical candidate facts used to fill external application forms.

Loaded from sender/apply_profile.yml (gitignored). Pure data — no I/O here.
"""
from dataclasses import dataclass, field


import re as _re

# Страна, названная в вопросе о праве работать. Формы спрашивают это десятком
# оборотов, и все они кончаются названием места: «Are you legally authorized to
# work in Sweden?», «Do you have the right to work in the UK?», «Are you eligible
# to work in the United States without sponsorship?».
# Страну спрашивают двумя разными оборотами, и оба нужны: «право работать в X»
# и «спонсорство для работы в X» — это один и тот же факт с разных сторон.
# Шаблоны намеренно узкие. Взять просто «to work in X» нельзя: под это подходят
# «to work in a team», «to work in a hybrid setting», «to work in Python», и
# страной оказалось бы что угодно.
#
# Русская форма нужна не для красоты: без неё «Имеете ли вы право работать в
# Казахстане?» читалось как «страна не названа» и получало ответ «нет» — мы
# отказывали себе в вакансии на родине.
_WHERE_RES = (
    _re.compile(
        r"(?:authori[sz]ed|eligible|permitted|legal(?:ly)?\s+able|right)\s+to\s+work\s+"
        r"(?:remotely\s+)?in\s+(?:the\s+)?([A-Za-zÀ-ÿ\u0400-\u04FF][\w'’\- ]{1,34})",
        _re.I),
    _re.compile(
        r"(?:sponsorship|sponsor(?:ed|ing)?)\s+(?:to\s+(?:work|be\s+employed)\s+)?"
        r"in\s+(?:the\s+)?([A-Za-zÀ-ÿ\u0400-\u04FF][\w'’\- ]{1,34})", _re.I),
    _re.compile(r"visa\s+(?:to\s+work\s+)?(?:in|for)\s+(?:the\s+)?"
                r"([A-Za-zÀ-ÿ\u0400-\u04FF][\w'’\- ]{1,34})", _re.I),
    _re.compile(r"(?:право\s+работать|правом\s+работать|разрешение\s+на\s+работу)"
                r"\s+в\s+([\u0400-\u04FF][\w'’\- ]{1,34})", _re.I),
)
# Синонимы одной страны. Список короткий намеренно: он покрывает то, что реально
# встречается в формах, а не географию вообще. Падежи здесь же — форма
# спрашивает «в КазахстанЕ», а в анкете стоит «Kazakhstan».
_ALIASES = {
    "kazakhstan": {"kazakhstan", "казахстан", "казахстане", "казахстана", "kz",
                   "republic of kazakhstan", "республика казахстан"},
    "united states": {"united states", "usa", "us", "united states of america", "america"},
    "united kingdom": {"united kingdom", "uk", "great britain", "britain"},
}


def _canon(name: str) -> str:
    n = _re.sub(r"\s+", " ", (name or "").strip().lower()).strip(" .,?!*")
    for canon, names in _ALIASES.items():
        if n in names:
            return canon
    return n


def country_in_question(question: str) -> str:
    """Страна, названная в вопросе, или "" — если её там нет."""
    for rx in _WHERE_RES:
        m = rx.search(question or "")
        if m:
            return m.group(1).strip(" .,?!*")
    return ""


def work_authorized_in(question: str, home_country: str) -> bool:
    """Есть ли право работать там, о чём спрашивает форма.

    Раньше на это отвечал ОДИН флаг `needs_visa_sponsorship`, и страна в вопросе
    не читалась вовсе. При `needs_visa_sponsorship=False` и `country=Kazakhstan`
    это означало «да, имею право работать» — в Швеции, в США, где угодно.
    Живьём 2026-09-01, LinkedIn Easy Apply: «Are you legally authorized to work
    in Sweden?*» -> «Yes». Это неправда, и хуже того — неправда, сказанная
    работодателю от имени человека.

    Правило теперь читает страну и сверяет её с домашней. Когда страна НЕ
    названа («Are you legally authorized to work?»), ответ «нет»: вопрос почти
    всегда про страну работодателя, а она у нас чужая, и ошибиться здесь лучше в
    сторону честного отказа — потерянная вакансия дешевле ложного заявления.
    """
    where = country_in_question(question)
    if not where:
        return False
    return _canon(where) == _canon(home_country)


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
    # Телеграм-ник в форме «@nick». Формы спрашивают его наравне с почтой
    # («Telegram handle»), а ответ на него обязан совпадать с тем, что уходит в
    # подписи письма, иначе работодатель получает два разных ника.
    telegram: str = ""
    github: str = ""
    portfolio: str = ""
    work_authorization: str = ""
    needs_visa_sponsorship: bool = False
    desired_salary: str = ""
    # Сколько лет опыта называть в ответ на вопрос «years of experience».
    # 0 = не подставлять число, оставить вопрос модели. Такой вопрос есть и в
    # формах ATS, и в LinkedIn Easy Apply, и часто он обязательный: без ответа
    # вся заявка уходит в `manual`, уже потратив генерацию письма и браузер.
    min_experience_years: int = 3
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
