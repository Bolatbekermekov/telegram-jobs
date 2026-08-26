"""Стоит ли заполнять СКРЫТОЕ поле даты — решение, отдельно от его исполнения.

Замер живьём 2026-08-26 на BlueThrone (лид #419): обязательный вопрос «Please
enter your available start date» нарисован как `input[type=date]` внутри блока
`hidden max-h-0`, то есть display:none. Блок не раскрывается ни при одном из
четырёх вариантов соседнего вопроса про доступность — проверены все. ATS при
этом ответ требует и отправку без него отклоняет, так что форма недоступна ни
нам, ни человеку, пока поле не заполнено.

Писать в невидимые контролы в общем случае нельзя: там лежат токены, скрытые
идентификаторы и служебные значения формы, и ошибка тут молча уходит
работодателю. Поэтому правило узкое настолько, насколько получилось: нужен
контрол именно типа `date`, его блок должен быть помечен обязательным, и
спрашивать он должен про НАШУ дату выхода. Дата выпуска и даты прошлых мест
работы под правило не попадают — их мы не знаем и выдумывать не станем.
"""
import re

from app.application.auto_apply import label_says_required

# Про наш выход на работу — и ничего больше. «graduation», «end date» и даты
# прошлых мест сюда намеренно не подходят.
_OURS_RE = re.compile(
    r"available\s+start\s+date|availability\s+to\s+start|start(?:ing)?\s+date\s+"
    r"(?:with\s+us|for\s+this\s+role)|when\s+can\s+you\s+start|"
    r"дата\s+выхода|когда\s+(?:готов|сможешь)", re.IGNORECASE)

_NOT_OURS_RE = re.compile(
    r"graduat|end\s+date|previous|last\s+employ|school|university|degree",
    re.IGNORECASE)


def wants_availability_date(block_text: str | None) -> bool:
    """Этот скрытый блок спрашивает нашу дату выхода и требует ответа."""
    text = (block_text or "").strip()
    if not text or _NOT_OURS_RE.search(text):
        return False
    return bool(_OURS_RE.search(text)) and label_says_required(text)
