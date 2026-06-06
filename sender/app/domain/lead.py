"""Domain entities for the sender. No external dependencies."""
from dataclasses import dataclass

# Fixed column order of the Google Sheet (must match the intake bot).
COLUMNS = [
    "id",
    "Дата добавления",
    "Исходный текст",
    "Ник/ссылка",
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

STATUS_NEW = "new"
STATUS_SENT = "sent"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"


@dataclass
class Lead:
    row: int               # 1-based row number in the sheet (incl. header offset)
    lead_id: str
    nickname: str          # @nick or t.me/...
    vacancy_context: str
    raw_text: str
    status: str
