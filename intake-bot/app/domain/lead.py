"""Domain entities. No external dependencies."""
from dataclasses import dataclass

# Fixed column order of the Google Sheet (Russian headers).
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

STATUS_NEW = "new"


@dataclass
class ExtractedLead:
    """Result of parsing a raw vacancy message."""

    nickname: str          # @nick or t.me/... — recipient
    vacancy_context: str   # role / conditions / salary, summarized
    raw_text: str          # original text the user sent

    def is_valid(self) -> bool:
        return bool(self.nickname.strip())
