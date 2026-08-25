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
    # Насколько вакансия подходит профилю поиска (0-100) и почему — тот же
    # вопрос, который поиск на ноуте задаёт о каждой найденной вакансии. None =
    # НЕ ОЦЕНИВАЛИ (модель не ответила, бюджет функции вышел, читать было
    # нечего), и это не то же самое, что 0: ноль — вердикт «совсем мимо».
    # Оценка ничего не отбрасывает, лид сохраняется при любой; см. sheet_note().
    score: int | None = None
    score_reason: str = ""

    def is_valid(self) -> bool:
        return bool(self.target.strip())

    def sheet_note(self) -> str:
        """Что уходит в колонку «Заметка».

        Отдельной колонки под оценку нет намеренно. Порядок COLUMNS общий с
        ноутбучной половиной и адресуется по индексу (там из него выведены
        COL_*), поэтому новая колонка — это правка в обеих копиях плюс живая
        таблица, и до тех пор `update_resolved` пишет свой диапазон мимо ячеек.
        «Заметка» же у нового лида почти всегда пуста, а перезаписывают её
        только `mark_status` при отправке — то есть уже после того, как оценка
        отработала своё дело: показать вакансию до генерации письма.

        Оценка идёт ПЕРВОЙ: маршрутная заметка длинная (в ней URL поста), а в
        таблице глазами видно начало ячейки.
        """
        if self.score is None:
            return self.note
        head = f"соответствие профилю {self.score}/100"
        if self.score_reason:
            head = f"{head}: {self.score_reason}"
        return f"{head} | {self.note}" if self.note else head
