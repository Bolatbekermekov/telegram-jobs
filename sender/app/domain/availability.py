"""Когда я смогу выйти — датой, а не словами.

Формы спрашивают срок выхода двумя способами. Текстом («Notice period») — туда
годится строка из профиля, «1 month». И контролом `input[type=date]`, который
принимает ТОЛЬКО YYYY-MM-DD: замер 2026-08-26 на BlueThrone показал, что строка
`1 month` в такой контрол не встаёт вовсе, и обязательное поле останавливало
всю заявку.

Считаем от срока отработки из профиля. Если срок записан так, что разобрать его
нельзя, возвращаем пусто: пустое поле удержит отправку и уведёт лид в ручной
отклик, а выдуманная дата уйдёт работодателю молча и станет обещанием, которого
никто не давал.
"""
import re
from calendar import monthrange
from datetime import date, timedelta

_NOW_RE = re.compile(r"immediat|asap|right away|сразу|немедленн|сейчас", re.IGNORECASE)
_SPAN_RE = re.compile(
    r"(\d+)\s*(day|days|week|weeks|month|months|дн|дня|дней|недел|месяц)", re.IGNORECASE)


def _plus_months(start: date, months: int) -> date:
    """То же число через N месяцев; 31 января + месяц = 28 февраля.

    Календарный месяц, а не 30 суток: «выйду через месяц» человек и работодатель
    читают как то же число следующего месяца.
    """
    total = start.month - 1 + months
    year = start.year + total // 12
    month = total % 12 + 1
    return date(year, month, min(start.day, monthrange(year, month)[1]))


def availability_iso(notice_period: str, today: date | None = None) -> str:
    """Дата выхода как YYYY-MM-DD, или "" если срок не разобран."""
    text = (notice_period or "").strip()
    if not text:
        return ""
    today = today or date.today()
    if _NOW_RE.search(text):
        return today.isoformat()
    m = _SPAN_RE.search(text)
    if not m:
        return ""
    n, unit = int(m.group(1)), m.group(2).lower()
    if unit.startswith(("day", "дн", "дня", "дне")):
        return (today + timedelta(days=n)).isoformat()
    if unit.startswith(("week", "недел")):
        return (today + timedelta(weeks=n)).isoformat()
    return _plus_months(today, n).isoformat()
