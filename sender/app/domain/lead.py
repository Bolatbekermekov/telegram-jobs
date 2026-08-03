"""Domain entities for the sender. No external dependencies."""
from dataclasses import dataclass
from datetime import datetime

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

# 1-based column indexes used for targeted cell updates, in sheet order.
COL_PLATFORM = COLUMNS.index("Платформа") + 1
COL_TARGET = COLUMNS.index("Источник") + 1
COL_VACANCY = COLUMNS.index("Вакансия") + 1
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
# A LinkedIn connection request went out WITHOUT the cover letter, because the
# monthly personalized-invite quota was spent. Not a send and not a failure: the
# lead is parked until the person accepts, and every later run re-checks it —
# accepted turns into a real message (with the CV), still pending stays here.
STATUS_INVITED = "invited"

# Default platform when the "Платформа" cell is empty (back-compat with old rows).
DEFAULT_PLATFORM = "telegram"


@dataclass
class Lead:
    row: int               # 1-based row number in the sheet (incl. header offset)
    lead_id: str
    platform: str          # telegram | linkedin | hh | email | wellfound | threads
    target: str            # @nick / profile URL / vacancy URL / email
    vacancy_context: str
    raw_text: str
    status: str
    # Когда мы обращались к этому человеку, если обращались и если дата
    # разобралась. Нужна циклу `invited`: он решает по ней, не пора ли перестать
    # ждать ответа на запрос контакта (app/domain/invite_age.py). У лида со
    # статусом `new` она всегда None.
    sent_at: datetime | None = None
