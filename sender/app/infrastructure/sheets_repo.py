"""Google Sheets repository for the sender: read `new` leads, update status."""
import datetime as _dt
import time

import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError
from gspread.utils import ValueInputOption, rowcol_to_a1

from app.domain.invite_age import EXPIRED_NOTE_PREFIX
from app.domain.lead import (
    COL_DATE_SENT,
    COL_MESSAGE,
    COL_NOTE,
    COL_PLATFORM,
    COL_STATUS,
    COL_VACANCY,
    COLUMNS,
    DEFAULT_PLATFORM,
    STATUS_INVITED,
    STATUS_NEW,
    STATUS_SENT,
    STATUS_SKIPPED,
    Lead,
)
from app.domain.outreach_history import SentRecord, normalize_address

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# 429 is the 60-writes-per-minute quota, 5xx is Google being briefly unavailable.
# A 403 (sheet not shared with the service account) or 400 (bad range) is a real
# misconfiguration — retrying hides it, so those must surface immediately.
_TRANSIENT_CODES = frozenset({429, 500, 502, 503, 504})
_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY_SECONDS = 1.0


def _status_of(exc: APIError) -> int:
    """The HTTP status behind an APIError — not necessarily its `code`.

    gspread reads `code` out of the JSON body and falls back to -1 when the body
    won't parse. Google's 5xx are served by the front end, *before* the API layer,
    as an HTML error page — so exactly the failures worth retrying are the ones
    that arrive with `code == -1`. Keying on `code` alone meant the retry below
    never fired on an outage, only on the quota errors that do come back as JSON.

    Falls back to `code` when there is no response to read (which is how the
    tests' hand-built errors and any future gspread change behave).
    """
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return status if isinstance(status, int) else exc.code


def _with_retry(op, attempts: int = _RETRY_ATTEMPTS, sleep=None):
    """Run a Sheets write, retrying transient API errors with exponential backoff.

    A write that fails *after* the message was already delivered is what leaves a
    lead `new` and gets it sent to the same person again on the next run, so the
    write path is worth retrying even though the read path is not.
    """
    _sleep = time.sleep if sleep is None else sleep
    for attempt in range(attempts):
        try:
            return op()
        except APIError as exc:
            if _status_of(exc) not in _TRANSIENT_CODES or attempt == attempts - 1:
                raise
            _sleep(_RETRY_BASE_DELAY_SECONDS * 2 ** attempt)


def _load_credentials(service_account_path: str) -> Credentials:
    return Credentials.from_service_account_file(service_account_path, scopes=_SCOPES)


# Что считается состоявшейся отправкой. `invited` входит намеренно: запрос на
# контакт в LinkedIn человеку уже ушёл, и второе обращение, пока он висит без
# ответа, выглядит навязчивым ровно так же, как повторное письмо.
_COMPLETED = frozenset({STATUS_SENT, STATUS_INVITED})

# Единственный формат, которым пишет `mark_sent`. Замер листа 2026-08-03: 117
# строк из 117 с датой соответствуют ему (одна — без ведущего нуля в часе,
# strptime это принимает). Всё остальное неразборчиво и не должно ронять прогон.
_SENT_AT_FORMAT = "%Y-%m-%d %H:%M"


def _parse_sent_at(raw) -> _dt.datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return _dt.datetime.strptime(text, _SENT_AT_FORMAT)
    except ValueError:
        # Дату не разобрать — но отправка была. Терять запись нельзя: без неё
        # адрес снова считается нетронутым. `duplicate_reason` трактует
        # неизвестную дату как «писали недавно», то есть в пользу молчания.
        return None


def _was_contacted(rec: dict) -> bool:
    """Дошло ли до человека хоть что-то — по статусу или по заметке.

    Закрытое по сроку приглашение уходит в `skipped`, но запрос на контакт
    человек УЖЕ получил. Без этой ветки такая строка выпадает из истории вместе
    со статусом, и защита от дублей снова считает адрес нетронутым — ровно в тот
    момент, когда мы решили больше его не трогать. Прочие `skipped` (rate-limit,
    сам дубль) сюда не попадают: у них другая заметка.
    """
    status = str(rec.get("Статус", "")).strip()
    if status in _COMPLETED:
        return True
    return (status == STATUS_SKIPPED
            and str(rec.get("Заметка", "")).strip().startswith(EXPIRED_NOTE_PREFIX))


def record_to_sent(rec: dict) -> SentRecord | None:
    """Строка листа -> запись в истории отправок, или None, если письма не было."""
    if not _was_contacted(rec):
        return None
    return SentRecord(
        platform=str(rec.get("Платформа", "")).strip().lower() or DEFAULT_PLATFORM,
        address=normalize_address(rec.get("Источник")),
        vacancy=str(rec.get("Вакансия", "")).strip(),
        sent_at=_parse_sent_at(rec.get("Дата отправки")),
        lead_id=str(rec.get("id", "")),
    )


def record_to_lead(rec: dict, offset: int, status: str = STATUS_NEW) -> Lead:
    """Map one sheet record to a Lead. `offset` is the 0-based data-row index."""
    platform = str(rec.get("Платформа", "")).strip().lower() or DEFAULT_PLATFORM
    return Lead(
        row=offset + 2,  # +1 header, +1 to 1-based
        lead_id=str(rec.get("id", "")),
        platform=platform,
        target=str(rec.get("Источник", "")).strip(),
        vacancy_context=str(rec.get("Вакансия", "")).strip(),
        raw_text=str(rec.get("Исходный текст", "")).strip(),
        status=status,
        sent_at=_parse_sent_at(rec.get("Дата отправки")),
    )


class SheetsRepo:
    def __init__(self, service_account_path: str, sheet_id: str, tab: str):
        client = gspread.authorize(_load_credentials(service_account_path))
        self._ws = client.open_by_key(sheet_id).worksheet(tab)

    def fetch_by_status(self, status: str) -> list[Lead]:
        """Every lead currently carrying `status`, in sheet order."""
        records = self._ws.get_all_records(expected_headers=COLUMNS)
        return [
            record_to_lead(rec, offset, status)
            for offset, rec in enumerate(records)
            if str(rec.get("Статус", "")).strip() == status
        ]

    def fetch_new_leads(self) -> list[Lead]:
        return self.fetch_by_status(STATUS_NEW)

    def fetch_sent_history(self) -> list[SentRecord]:
        """Всё, что уже ушло людям, — чтобы не написать кому-то дважды.

        Один запрос на прогон: лист читается целиком и так, а история нужна
        до первой отправки.
        """
        records = self._ws.get_all_records(expected_headers=COLUMNS)
        return [r for r in (record_to_sent(rec) for rec in records) if r is not None]

    def mark_sent(self, lead: Lead, message: str, status: str,
                  note: str = "") -> None:
        """Record a delivered outreach — message, status and timestamp at once.

        Сообщение / Статус / Дата отправки are adjacent columns, so this is one
        ranged write: a single API call that either lands whole or not at all.
        Three separate update_cell calls could half-apply and leave the lead
        `new` with the message already delivered, which the next run would read
        as unsent and deliver a second time.

        RAW, not USER_ENTERED: the body is model-generated from a scraped
        vacancy, so a leading `=` must be stored as text, never evaluated as a
        formula.
        """
        now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        # «Заметка» стоит сразу за «Датой отправки», поэтому она уезжает тем же
        # ранговым write-ом — отдельный вызов мог бы лечь только наполовину.
        # Без заметки диапазон намеренно короче: пустая строка затёрла бы то,
        # что там уже написано (например, причину прошлой неудачи).
        values = [message, status, now]
        last_col = COL_DATE_SENT
        if note:
            values.append(note)
            last_col = COL_NOTE
        cells = (f"{rowcol_to_a1(lead.row, COL_MESSAGE)}"
                 f":{rowcol_to_a1(lead.row, last_col)}")
        _with_retry(lambda: self._ws.update(
            [values],
            cells,
            value_input_option=ValueInputOption.raw,
        ))

    def mark_invited(self, lead: Lead, note: str = "") -> None:
        """Запрос на контакт ушёл без письма — статус, дата и заметка разом.

        Дата здесь не формальность: пока её не было, цикл `invited` не мог
        узнать, сколько приглашение висит, и проверял его вечно (лид #79 —
        17 дней подряд). Формат тот же, что у `mark_sent`, потому что читает
        обе записи один и тот же `_parse_sent_at`.

        Статус / Дата отправки / Заметка стоят подряд, поэтому это один ранговый
        write — он либо ложится целиком, либо не ложится вовсе. «Сообщение»
        диапазон не задевает намеренно: письма не было, и записывать туда текст
        значило бы утверждать, что человек его получил.
        """
        now = _dt.datetime.now().strftime(_SENT_AT_FORMAT)
        cells = (f"{rowcol_to_a1(lead.row, COL_STATUS)}"
                 f":{rowcol_to_a1(lead.row, COL_NOTE)}")
        _with_retry(lambda: self._ws.update(
            [[STATUS_INVITED, now, note]],
            cells,
            value_input_option=ValueInputOption.raw,
        ))

    def mark_status(self, lead: Lead, status: str, note: str = "") -> None:
        """Set a lead's status, and its note when there is one, in one API call.

        Статус and Заметка are not adjacent (Дата отправки sits between them),
        so this batches two ranges rather than writing one span — writing the
        span would blank the send timestamp.

        `invited` через этот метод не ставится: он не пишет дату, а приглашение
        без даты цикл `invited` закрывает на следующем же прогоне. Пусть
        неправильный путь падает здесь, а не тихо убивает лид сутки спустя.
        """
        if status == STATUS_INVITED:
            raise ValueError(
                "invited ставится через mark_invited: без «Даты отправки» "
                "приглашение будет закрыто на следующем прогоне")
        # Payload собирается ЗАНОВО на каждую попытку. gspread дописывает имя
        # листа прямо в переданный словарь (`values["range"] =
        # absolute_range_name(self.title, …)`), поэтому повтор с тем же объектом
        # отправлял «'Лист1'!'Лист1'!H414» и получал 400 — а 400 не транзиентный
        # и летел наружу. Замер 2026-08-25 на живой 502 от Google.
        #
        # Это ровно тот случай, ради которого повтор написан: запись падает ПОСЛЕ
        # доставки сообщения, лид остаётся `new`, и следующий прогон пишет тому
        # же человеку второй раз. Защита ломалась именно тогда, когда нужна.
        def _payload():
            updates = [{
                "range": rowcol_to_a1(lead.row, COL_STATUS),
                "values": [[status]],
            }]
            if note:
                updates.append({
                    "range": rowcol_to_a1(lead.row, COL_NOTE),
                    "values": [[note]],
                })
            return updates

        _with_retry(lambda: self._ws.batch_update(
            _payload(), value_input_option=ValueInputOption.raw))

    def update_vacancy(self, lead: Lead, vacancy_context: str) -> None:
        """Replace a lead's «Вакансия» text, leaving every other column alone.

        The narrow counterpart to `update_resolved`: where the lead goes does not
        change, only what it says. A link-only message whose page would not load
        at intake time is saved with this column empty rather than with the
        summariser's refusal in it, and the laptop fills it in here — one cell, so
        the atomicity `update_resolved` has to work for is free.

        Статус is deliberately untouched: the lead has not been sent, it stays
        `new` and goes on to be generated and delivered in this same run.

        RAW, not USER_ENTERED: the text is scraped, so a leading `=` must be
        stored as text, never evaluated as a formula.
        """
        _with_retry(lambda: self._ws.update(
            [[vacancy_context]],
            rowcol_to_a1(lead.row, COL_VACANCY),
            value_input_option=ValueInputOption.raw,
        ))

    def update_resolved(self, lead: Lead, platform: str, target: str,
                        vacancy_context: str, note: str = "") -> None:
        """Rewrite where a lead goes and what it says, in one API call.

        A Threads lead arrives pointing at a post URL carrying only the root
        post's text. Once the thread is read the real contact is usually
        somewhere else entirely ("Для отклика присылайте портфолио в Telegram:
        @…"), so platform, target and vacancy text all change together.

        Платформа / Источник / Вакансия are adjacent columns, so they go as one
        span. Заметка is a separate range: Сообщение / Статус / Дата отправки
        sit between, and one wide span would blank the message and the send
        timestamp.

        Статус is deliberately untouched — the lead has not been sent yet, it
        stays `new`. A half-applied rewrite is the worst outcome available here:
        a lead labelled telegram whose target is still a Threads URL, which the
        send loop would try to DM as if it were a handle. Hence one atomic write.

        RAW, not USER_ENTERED: the vacancy text is scraped, so a leading `=`
        must be stored as text, never evaluated as a formula.
        """
        # Заново на каждую попытку — по той же причине, что и в `mark_status`:
        # gspread портит переданный payload, дописывая в него имя листа.
        def _payload():
            updates = [{
                "range": (f"{rowcol_to_a1(lead.row, COL_PLATFORM)}"
                          f":{rowcol_to_a1(lead.row, COL_VACANCY)}"),
                "values": [[platform, target, vacancy_context]],
            }]
            if note:
                updates.append({
                    "range": rowcol_to_a1(lead.row, COL_NOTE),
                    "values": [[note]],
                })
            return updates

        _with_retry(lambda: self._ws.batch_update(
            _payload(), value_input_option=ValueInputOption.raw))
