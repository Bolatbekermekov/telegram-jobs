"""Domain entities for the sender. No external dependencies."""
from dataclasses import dataclass

# Fixed column order of the Google Sheet (must match the intake bot).
COLUMNS = [
    "id",
    "Дата добавления",
    "Исходный текст",
    "Платформа",
    "Источник",
    "Вакансия",
    "Сообщение",
    "Статус",
    "Дата отправки",
    "Заметка",
]

# 1-based column indexes used for targeted cell updates.
COL_MESSAGE = COLUMNS.index("Сообщение") + 1
COL_STATUS = COLUMNS.index("Статус") + 1
COL_DATE_SENT = COLUMNS.index("Дата отправки") + 1
COL_NOTE = COLUMNS.index("Заметка") + 1

STATUS_NEW = "new"
STATUS_SENT = "sent"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"
# Apply couldn't be automated (CAPTCHA/login/unknown form) — do it by hand.
STATUS_MANUAL = "manual"

# Default platform when the "Платформа" cell is empty (back-compat with old rows).
DEFAULT_PLATFORM = "telegram"


@dataclass
class Lead:
    row: int               # 1-based row number in the sheet (incl. header offset)
    lead_id: str
    platform: str          # telegram | linkedin | hh | email | wellfound
    target: str            # @nick / profile URL / vacancy URL / email
    vacancy_context: str
    raw_text: str
    status: str
