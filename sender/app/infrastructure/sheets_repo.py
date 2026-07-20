"""Google Sheets repository for the sender: read `new` leads, update status."""
import datetime as _dt
import time

import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError
from gspread.utils import ValueInputOption, rowcol_to_a1

from app.domain.lead import (
    COL_DATE_SENT,
    COL_MESSAGE,
    COL_NOTE,
    COL_STATUS,
    COLUMNS,
    DEFAULT_PLATFORM,
    STATUS_NEW,
    Lead,
)

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# 429 is the 60-writes-per-minute quota, 5xx is Google being briefly unavailable.
# A 403 (sheet not shared with the service account) or 400 (bad range) is a real
# misconfiguration — retrying hides it, so those must surface immediately.
_TRANSIENT_CODES = frozenset({429, 500, 502, 503, 504})
_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY_SECONDS = 1.0


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
            if exc.code not in _TRANSIENT_CODES or attempt == attempts - 1:
                raise
            _sleep(_RETRY_BASE_DELAY_SECONDS * 2 ** attempt)


def _load_credentials(service_account_path: str) -> Credentials:
    return Credentials.from_service_account_file(service_account_path, scopes=_SCOPES)


def record_to_lead(rec: dict, offset: int) -> Lead:
    """Map one sheet record to a Lead. `offset` is the 0-based data-row index."""
    platform = str(rec.get("Платформа", "")).strip().lower() or DEFAULT_PLATFORM
    return Lead(
        row=offset + 2,  # +1 header, +1 to 1-based
        lead_id=str(rec.get("id", "")),
        platform=platform,
        target=str(rec.get("Источник", "")).strip(),
        vacancy_context=str(rec.get("Вакансия", "")).strip(),
        raw_text=str(rec.get("Исходный текст", "")).strip(),
        status=STATUS_NEW,
    )


class SheetsRepo:
    def __init__(self, service_account_path: str, sheet_id: str, tab: str):
        client = gspread.authorize(_load_credentials(service_account_path))
        self._ws = client.open_by_key(sheet_id).worksheet(tab)

    def fetch_new_leads(self) -> list[Lead]:
        records = self._ws.get_all_records(expected_headers=COLUMNS)
        return [
            record_to_lead(rec, offset)
            for offset, rec in enumerate(records)
            if str(rec.get("Статус", "")).strip() == STATUS_NEW
        ]

    def mark_sent(self, lead: Lead, message: str, status: str) -> None:
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
        cells = (f"{rowcol_to_a1(lead.row, COL_MESSAGE)}"
                 f":{rowcol_to_a1(lead.row, COL_DATE_SENT)}")
        _with_retry(lambda: self._ws.update(
            [[message, status, now]],
            cells,
            value_input_option=ValueInputOption.raw,
        ))

    def mark_status(self, lead: Lead, status: str, note: str = "") -> None:
        """Set a lead's status, and its note when there is one, in one API call.

        Статус and Заметка are not adjacent (Дата отправки sits between them),
        so this batches two ranges rather than writing one span — writing the
        span would blank the send timestamp.
        """
        updates = [{
            "range": rowcol_to_a1(lead.row, COL_STATUS),
            "values": [[status]],
        }]
        if note:
            updates.append({
                "range": rowcol_to_a1(lead.row, COL_NOTE),
                "values": [[note]],
            })
        _with_retry(lambda: self._ws.batch_update(
            updates, value_input_option=ValueInputOption.raw))
