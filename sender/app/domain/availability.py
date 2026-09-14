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


# В КАКИХ единицах спрашивают. Живьём 2026-09-05 три разных написания одного
# вопроса за один прогон: «notice period (in weeks)», «notice period in days»,
# «notice period?». Профиль хранит одну строку — «1 month», — и она уезжала во
# все три как есть. LinkedIn отвечал «Недопустимое значение», экран не менялся,
# и обход упирался в предел шагов, ничего не сказав.
_ASKED_UNIT_RE = re.compile(
    r"\b(?:in\s+)?(day|week|month)s?\b|\((?:in\s+)?(day|week|month)s?\)"
    r"|в\s+(дн|недел|месяц)", re.IGNORECASE)
_DAYS_PER = {"day": 1, "week": 7, "month": 30}


def _asked_unit(question: str) -> str:
    m = _ASKED_UNIT_RE.search(question or "")
    if not m:
        return ""
    got = (m.group(1) or m.group(2) or m.group(3) or "").lower()
    if got.startswith("дн"):
        return "day"
    if got.startswith("недел"):
        return "week"
    if got.startswith("месяц"):
        return "month"
    return got


def notice_period_in(question: str, notice_period: str) -> str:
    """Срок отработки числом в тех единицах, которые называет вопрос.

    Пустая строка — когда переводить не во что или не из чего: вопрос без
    единицы («Notice period?») получает строку профиля как была, а неразборчивый
    срок не превращается в выдуманное число. Ноль недель для «immediately» —
    честный ответ, а не отсутствие ответа.

    Месяц считается за 30 дней, и «1 month» в неделях даёт 4, а не 5: столько
    недель в месяце для человека, читающего анкету, и округление вниз здесь
    занижает срок, то есть говорит в нашу пользу, но не завышает обещание.
    """
    unit = _asked_unit(question)
    if not unit:
        return ""
    days = _notice_days(notice_period)
    if days is None:
        return ""
    return str(max(0, round(days / _DAYS_PER[unit])))


def _notice_days(notice_period: str) -> int | None:
    """Срок отработки в днях (месяц — 30 дней), или None, если он не разобран."""
    text = (notice_period or "").strip()
    if not text:
        return None
    if _NOW_RE.search(text):
        return 0
    m = _SPAN_RE.search(text)
    if not m:
        return None
    n, got = int(m.group(1)), m.group(2).lower()
    if got.startswith(("day", "дн")):
        return n
    if got.startswith(("week", "недел")):
        return n * 7
    return n * 30


# Варианты списка «срок выхода»: «Immediate Joiner», «Less than 30 Days»,
# «16-30 days», «1 month», «2+ months», «More than 1 month».
_OPTION_UNIT = r"(day|week|month|дн|недел|месяц)"
_OPTION_RANGE_RE = re.compile(r"(\d+)\s*(?:[-–—]|to|до)\s*(\d+)\s*" + _OPTION_UNIT,
                              re.IGNORECASE)
_OPTION_ONE_RE = re.compile(r"(\d+)\s*(\+)?\s*" + _OPTION_UNIT, re.IGNORECASE)
# «no more than» и «не более» содержат «more than» и «более» — поэтому «не
# больше N» проверяется раньше «больше N».
_OPTION_UP_TO_RE = re.compile(r"within|up to|no more than|не более|\bдо\b", re.IGNORECASE)
_OPTION_BELOW_RE = re.compile(r"less than|under|below|fewer than|менее|меньше", re.IGNORECASE)
_OPTION_ABOVE_RE = re.compile(r"more than|over|above|longer than|beyond|более|больше|свыше",
                              re.IGNORECASE)


def _unit_days(unit: str) -> int:
    u = unit.lower()
    if u.startswith(("week", "недел")):
        return 7
    if u.startswith(("month", "месяц")):
        return 30
    return 1


def _option_days(option: str) -> tuple[int, float] | None:
    """(от, до) в днях, которые покрывает вариант, или None — если чисел в нём нет."""
    text = option or ""
    if _NOW_RE.search(text):
        return (0, 0)
    m = _OPTION_RANGE_RE.search(text)
    if m:
        k = _unit_days(m.group(3))
        return (int(m.group(1)) * k, int(m.group(2)) * k)
    m = _OPTION_ONE_RE.search(text)
    if not m:
        return None
    n = int(m.group(1)) * _unit_days(m.group(3))
    if _OPTION_UP_TO_RE.search(text):
        return (0, n)
    if _OPTION_BELOW_RE.search(text):
        return (0, n - 1)
    if m.group(2):
        return (n, float("inf"))
    if _OPTION_ABOVE_RE.search(text):
        return (n + 1, float("inf"))
    return (n, n)


def notice_option_index(options: list[str], notice_period: str) -> int | None:
    """Номер варианта «срок выхода», в который попадает срок из анкеты, или None.

    Живьём 2026-09-14 (лид #1216, LinkedIn Easy Apply, шаг 6/8): «What is your
    current notice period?*» — «Immediate Joiner / Less than 30 Days / 30 Days /
    45 Days / 60 Days». Строка «1 month» буквально ни с чем не совпала, вопрос
    ушёл модели, её ответ в список не встал, и отклик остановился. Сравнение по
    дням этого не допускает: месяц — это вариант «30 Days».
    """
    days = _notice_days(notice_period)
    if days is None:
        return None
    for i, option in enumerate(options):
        span = _option_days(option)
        if span and span[0] <= days <= span[1]:
            return i
    return None
