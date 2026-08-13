"""Domain entities. No external dependencies."""
from dataclasses import dataclass

# Fixed column order of the Google Sheet (Russian headers).
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

STATUS_NEW = "new"


@dataclass
class ExtractedLead:
    """Result of parsing a raw vacancy message."""

    platform: str          # telegram | email | linkedin | hh | wellfound | threads
    target: str            # @nick / t.me / email / profile or vacancy URL (stored in «Источник»)
    vacancy_context: str   # role / conditions / salary, summarized
    raw_text: str          # original text the user sent
    # Why this lead points where it does, when that was not obvious from the
    # message: a contact read out of a LinkedIn post's body re-points the lead at
    # a Telegram handle nobody typed, and «Заметка» is the only place that decision
    # is visible in the sheet. Defaults to "" so the ordinary path is unchanged.
    note: str = ""

    def is_valid(self) -> bool:
        return bool(self.target.strip())
