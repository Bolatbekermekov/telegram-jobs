"""Найденная вакансия -> строка лида в основной вкладке, сразу и без разрешения.

Раньше между поиском и рассылкой стоял человек: поиск писал во вкладку
«Кандидаты» со статусом `pending`, бот присылал карточку с кнопками ✅/❌, и
только нажатие ✅ копировало строку в основную вкладку. По решению владельца
(2026-08-22) подтверждения больше нет — ни на ноуте, ни с телефона. Что нашлось
и прошло скоринг релевантности, то сразу становится лидом `new`, и ближайший
прогон его отправляет.

Отбор при этом не исчез, просто он теперь целиком автоматический:
`run_search` прогоняет найденное через `score_and_filter` (порог
MATCH_THRESHOLD), и сюда доезжает только то, что модель сочла подходящим.

Вкладка «Кандидаты» превращается в архив. Новых строк туда не пишется, но
старые продолжают читаться при дедупликации — среди них есть вакансии, которые
владелец когда-то отклонил кнопкой ❌, и им незачем возвращаться теперь, когда
отклонять нечем.
"""
import datetime as _dt

from app.domain.candidate import CANDIDATE_COLUMNS, Candidate, normalize_url
from app.domain.lead import COLUMNS, STATUS_NEW


def _vacancy_text(c: Candidate) -> str:
    """Текст, из которого потом пишется сопроводительное письмо.

    Кнопочный путь складывал сюда «Title — Summary» и терял компанию, вилку и
    локацию: карточку с ними человек видел в телеграме, а в таблицу они не
    доезжали. Писать письмо, не зная имени работодателя, нельзя, поэтому здесь
    собирается всё, что отдала площадка.

    Пустые поля не оставляют после себя пустых подписей: «Зарплата: .» в брифе
    хуже, чем отсутствие строки, — модель принимает её за факт «зарплата не
    указана» и иногда о нём пишет.
    """
    head = " — ".join(p for p in (c.title, c.company) if p)
    facts = ", ".join(p for p in (f"Зарплата: {c.salary}" if c.salary else "",
                                  f"Локация: {c.location}" if c.location else "") if p)
    return "\n".join(p for p in (head, facts, c.summary) if p)


def candidate_to_lead_row(c: Candidate, row_id, now: str) -> list:
    """Позиционная строка основной вкладки, в порядке COLUMNS, со статусом `new`.

    «Сообщение» и «Дата отправки» остаются пустыми намеренно: ничего ещё не
    отправлено, а непустая «Дата отправки» читается историей как состоявшийся
    контакт и закрыла бы лид, ни разу его не отправив.
    """
    vacancy = _vacancy_text(c)
    values = {
        "id": row_id,
        "Дата добавления": now,
        "Исходный текст": vacancy,
        "Платформа": c.platform,
        "Источник": c.url,
        "Вакансия": vacancy,
        "Сообщение": "",
        "Статус": STATUS_NEW,
        "Дата отправки": "",
        "Заметка": "",
    }
    return [values[name] for name in COLUMNS]


def should_add(c: Candidate, seen_keys: set, platform_new: int, cap: int) -> bool:
    """Новая (URL не встречался) и площадка не выбрала свой потолок.

    Потолок считает лиды, которые ЕЩЁ НЕ ОБРАБОТАНЫ (`new`), а не всё найденное
    когда-либо: он бережёт от того, чтобы один поиск вывалил в очередь двести
    строк, и отпускает по мере того, как прогон их разбирает. Это не фильтр
    качества и не замена ушедшей кнопке — за качество отвечает скоринг.
    """
    if platform_new >= cap:
        return False
    return normalize_url(c.url) not in seen_keys


class SearchLeadsRepo:
    def __init__(self, main_worksheet, legacy_candidates_worksheet, cap: int):
        self._main = main_worksheet      # основная вкладка лидов
        self._legacy = legacy_candidates_worksheet   # «Кандидаты», только чтение
        self._cap = cap

    def _seen_keys(self) -> set:
        """URL-ы, которые нам уже известны, из ОБЕИХ вкладок.

        Из основной — чтобы не написать человеку дважды. Из «Кандидатов» — чтобы
        не воскресить то, что когда-то отклонили руками (и то, что ушло в работу
        до этой правки).
        """
        keys = set()
        for tgt in self._main.col_values(COLUMNS.index("Источник") + 1)[1:]:
            if tgt and "http" in tgt:
                keys.add(normalize_url(tgt))
        if self._legacy is not None:
            for url in self._legacy.col_values(CANDIDATE_COLUMNS.index("URL") + 1)[1:]:
                if url:
                    keys.add(normalize_url(url))
        return keys

    def _new_counts(self) -> dict:
        """Сколько необработанных лидов уже стоит в очереди по каждой площадке."""
        plats = self._main.col_values(COLUMNS.index("Платформа") + 1)[1:]
        stats = self._main.col_values(COLUMNS.index("Статус") + 1)[1:]
        counts: dict = {}
        for platform, status in zip(plats, stats):
            if status == STATUS_NEW:
                counts[platform] = counts.get(platform, 0) + 1
        return counts

    def _next_id(self) -> int:
        return max(len(self._main.col_values(1)) - 1, 0) + 1

    def known_urls(self) -> set:
        """Известные URL-ы — для отсева ДО скоринга, чтобы не платить за дубли."""
        return self._seen_keys()

    def add_new(self, candidates) -> int:
        """Записать подошедших лидами `new`. Возвращает, сколько записано."""
        seen = self._seen_keys()
        counts = self._new_counts()
        now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        added = 0
        for c in candidates:
            if not should_add(c, seen, counts.get(c.platform, 0), self._cap):
                continue
            self._main.append_row(candidate_to_lead_row(c, self._next_id(), now),
                                  value_input_option="USER_ENTERED", table_range="A1")
            seen.add(normalize_url(c.url))
            counts[c.platform] = counts.get(c.platform, 0) + 1
            added += 1
        return added
