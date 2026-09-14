"""Дата рождения — одна строка в анкете, а в поле формы — в том виде, что ждёт поле.

Живьём 2026-09-14 (лид #1216, GeekSoft Consulting, LinkedIn Easy Apply, шаг
5/8): обязательное «Date Of Birth *» — текстовый вход календаря
(`data-testid="date-picker-input" lang="en-US"`) без placeholder. Даты рождения
в анкете не было, и отклик ушёл в ручной. Владелец назвал дату, в
`apply_profile.yml` она лежит как YYYY-MM-DD.

Формат выбирает поле — как именно, см. `date_format.date_for_field`.

Возраст считается от даты, а не хранится: прежнее `age: "22"` в анкете было
записано 2026-07-29 и разошлось с правдой.
"""
import re
from datetime import date

from app.domain.date_format import date_for_field, parse_iso

_DOB_RE = re.compile(
    r"date\s+of\s+birth|birth\s*date|birthday|\bd\.?o\.?b\b|"
    r"дата\s+рождения|день\s+рождения|geburtsdatum|fecha\s+de\s+nacimiento|"
    r"date\s+de\s+naissance|data\s+di\s+nascita|data\s+de\s+nascimento", re.IGNORECASE)
_AGE_RE = re.compile(r"\bage\b|how old|возраст|сколько\s+(?:вам\s+)?лет", re.IGNORECASE)
# Нижняя граница, о которой спрашивают «да/нет»: «Are you at least 18 years of
# age?», «over the age of 18», «18 or older», «18+», «не младше 18».
_MIN_AGE_RE = re.compile(
    r"(?:at\s+least|over|older\s+than|above|age\s+of|не\s+младше|старше)\s+(\d{2})\b"
    r"|\b(\d{2})\s*(?:\+|(?:years?\s+)?(?:of\s+age\s+)?or\s+(?:older|over|above)"
    r"|лет\s+и\s+старше)", re.IGNORECASE)


def asks_date_of_birth(text: str) -> bool:
    return bool(_DOB_RE.search(text or ""))


def asks_age(text: str) -> bool:
    """Вопрос о возрасте — но не о дате рождения: у той свой ответ."""
    return bool(_AGE_RE.search(text or "")) and not asks_date_of_birth(text)


def minimum_age_asked(text: str) -> int | None:
    """Порог из вопроса «вам есть N?», или None, если вопрос не про порог."""
    m = _MIN_AGE_RE.search(text or "")
    return int(m.group(1) or m.group(2)) if m else None


def age_on(iso: str, today: date) -> int | None:
    """Полных лет на `today`, или None, если даты рождения нет."""
    born = parse_iso(iso)
    if born is None:
        return None
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def birth_date_text(iso: str, field_type: str = "", placeholder: str = "",
                    lang: str = "", picker: bool = False) -> str:
    """Дата рождения в формате поля, или "" — если даты в анкете нет."""
    return date_for_field(iso, field_type=field_type, placeholder=placeholder,
                          lang=lang, picker=picker)
