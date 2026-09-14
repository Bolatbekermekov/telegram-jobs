"""Дата рождения — одна строка в анкете, а в поле формы — в том виде, что ждёт поле.

Живьём 2026-09-14 (лид #1216, GeekSoft Consulting, LinkedIn Easy Apply, шаг
5/8): обязательное «Date Of Birth *» — текстовый вход календаря
(`data-testid="date-picker-input" lang="en-US"`) без placeholder. Даты рождения
в анкете не было, и отклик ушёл в ручной. Владелец назвал дату, в
`apply_profile.yml` она лежит как YYYY-MM-DD.

Формат выбирает поле: placeholder называет порядок и разделитель («DD/MM/YYYY»,
«ДД.ММ.ГГГГ»), `input[type=date]` принимает только ISO, календарь LinkedIn на
en-US ждёт месяц первым. Без подсказки — ISO: «30/01» и «01/30» в разных странах
читают по-разному, а 2005-01-30 везде одинаково.

Возраст считается от даты, а не хранится: прежнее `age: "22"` в анкете было
записано 2026-07-29 и разошлось с правдой.
"""
import re
from datetime import date

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
# Части даты в подсказке поля. Отдельными «словами»: буква d из «Select date»
# частью даты не считается.
_PART_RE = re.compile(r"(?<![a-zа-яё])([dд]{1,2}|[mм]{1,2}|[yг]{2,4})(?![a-zа-яё])",
                      re.IGNORECASE)
_PART_KIND = {"d": "d", "д": "d", "m": "m", "м": "m", "y": "y", "г": "y"}


def asks_date_of_birth(text: str) -> bool:
    return bool(_DOB_RE.search(text or ""))


def asks_age(text: str) -> bool:
    """Вопрос о возрасте — но не о дате рождения: у той свой ответ."""
    return bool(_AGE_RE.search(text or "")) and not asks_date_of_birth(text)


def minimum_age_asked(text: str) -> int | None:
    """Порог из вопроса «вам есть N?», или None, если вопрос не про порог."""
    m = _MIN_AGE_RE.search(text or "")
    return int(m.group(1) or m.group(2)) if m else None


def _parse(iso: str) -> date | None:
    try:
        return date.fromisoformat((iso or "").strip())
    except ValueError:
        return None


def age_on(iso: str, today: date) -> int | None:
    """Полных лет на `today`, или None, если даты рождения нет."""
    born = _parse(iso)
    if born is None:
        return None
    return today.year - born.year - ((today.month, today.day) < (born.month, born.day))


def _by_placeholder(born: date, placeholder: str) -> str:
    parts = list(_PART_RE.finditer(placeholder or ""))
    kinds = [_PART_KIND[m.group(1)[0].lower()] for m in parts]
    if len(parts) != 3 or sorted(kinds) != ["d", "m", "y"]:
        return ""
    sep = placeholder[parts[0].end():parts[1].start()]
    out = []
    for m, kind in zip(parts, kinds):
        if kind == "y":
            out.append(str(born.year) if len(m.group(1)) >= 4 else f"{born.year % 100:02d}")
        else:
            out.append(f"{born.day if kind == 'd' else born.month:02d}")
    return sep.join(out)


def birth_date_text(iso: str, field_type: str = "", placeholder: str = "",
                    lang: str = "", picker: bool = False) -> str:
    """Дата рождения в формате поля, или "" — если даты в анкете нет."""
    born = _parse(iso)
    if born is None:
        return ""
    if field_type == "date":
        return born.isoformat()
    shaped = _by_placeholder(born, placeholder)
    if shaped:
        return shaped
    if picker and (lang or "").lower() == "en-us":
        return f"{born.month:02d}/{born.day:02d}/{born.year}"
    return born.isoformat()
