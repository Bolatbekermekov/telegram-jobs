"""Дата в том виде, в котором её ждёт поле формы.

Вынесено из birth_date 2026-09-14: тот же разбор формата понадобился и для даты
выхода — Indeed Apply держит «What is your last working date?» простым текстовым
полем, а формат `MM/dd/yyyy` кладёт в данные страницы (лид #1228).

Формат выбирает поле: placeholder называет порядок и разделитель («DD/MM/YYYY»,
«ДД.ММ.ГГГГ»), `input[type=date]` принимает только ISO, календарь LinkedIn на
en-US ждёт месяц первым. Без подсказки — ISO: «30/01» и «01/30» в разных странах
читают по-разному, а 2005-01-30 везде одинаково.
"""
import re
from datetime import date

# Части даты в подсказке поля. Отдельными «словами»: буква d из «Select date»
# частью даты не считается.
_PART_RE = re.compile(r"(?<![a-zа-яё])([dд]{1,2}|[mм]{1,2}|[yг]{2,4})(?![a-zа-яё])",
                      re.IGNORECASE)
_PART_KIND = {"d": "d", "д": "d", "m": "m", "м": "m", "y": "y", "г": "y"}


def parse_iso(iso) -> date | None:
    try:
        return date.fromisoformat(str(iso or "").strip())
    except ValueError:
        return None


def _parts(pattern: str) -> list:
    """(совпадение, «d»/«m»/«y») для подсказки ровно из дня, месяца и года, иначе []."""
    found = [(m, _PART_KIND[m.group(1)[0].lower()]) for m in _PART_RE.finditer(pattern or "")]
    if len(found) != 3 or sorted(kind for _, kind in found) != ["d", "m", "y"]:
        return []
    return found


def looks_like_date_pattern(text: str) -> bool:
    """«MM/dd/yyyy», «ДД.ММ.ГГГГ» — да; «Select date», пусто — нет."""
    return bool(_parts(text))


def _by_pattern(day: date, pattern: str) -> str:
    found = _parts(pattern)
    if not found:
        return ""
    sep = pattern[found[0][0].end():found[1][0].start()]
    out = []
    for m, kind in found:
        if kind == "y":
            out.append(str(day.year) if len(m.group(1)) >= 4 else f"{day.year % 100:02d}")
        else:
            out.append(f"{day.day if kind == 'd' else day.month:02d}")
    return sep.join(out)


def date_for_field(iso: str, field_type: str = "", placeholder: str = "",
                   lang: str = "", picker: bool = False) -> str:
    """ISO-дата в формате поля, или "" — если даты нет."""
    day = parse_iso(iso)
    if day is None:
        return ""
    if field_type == "date":
        return day.isoformat()
    shaped = _by_pattern(day, placeholder)
    if shaped:
        return shaped
    if picker and (lang or "").lower() == "en-us":
        return f"{day.month:02d}/{day.day:02d}/{day.year}"
    return day.isoformat()
