"""Domain entities. No external dependencies."""
from dataclasses import dataclass

# Fixed column order of the Google Sheet (Russian headers).
COLUMNS = [
    "id",
    "Дата добавления",
    "Исходный текст",
    "Платформа",
    "Цель",
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

    platform: str          # telegram | email | linkedin | hh | wellfound
    target: str            # @nick / t.me / email / profile or vacancy URL (stored in «Цель»)
    vacancy_context: str   # role / conditions / salary, summarized
    raw_text: str          # original text the user sent

    def is_valid(self) -> bool:
        return bool(self.target.strip())
