"""Google Sheets repository (gspread). Appends new leads with status=new.

Two deliberate choices here, both mirroring the sender's repo:

RAW, never USER_ENTERED. The row carries `raw_text` — a message forwarded from
somewhere else, written by someone who is not the user — and `vacancy_context`,
which the model wrote from a scraped page. USER_ENTERED evaluates a leading `=`,
so either of those could arrive as a live formula, and `=IMPORTXML(...)` in a
sheet is a way to send its contents to an outside host. RAW costs the date cells
their date type; that is the cheaper side of the trade.

Reads retry, the append does not. A retried append can duplicate a row when the
write landed and only the response was lost — and a duplicated lead is a second
identical message to the same recruiter. A lost lead just means resending the
link, so the asymmetry decides it.
"""
import datetime as _dt
import json
import time

import gspread
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError

from app.domain.lead import COLUMNS, STATUS_NEW, ExtractedLead

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_STATUS_COL = COLUMNS.index("Статус") + 1  # 1-based column number

# 429 is the write quota, 5xx is Google being briefly unavailable. A 403 (sheet
# not shared with the service account) or 400 (bad range) is a real
# misconfiguration — retrying hides it, so those must surface immediately.
_TRANSIENT_CODES = frozenset({429, 500, 502, 503, 504})
_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY_SECONDS = 1.0


def _status_of(exc: APIError) -> int:
    """The HTTP status behind an APIError — not necessarily its `code`.

    gspread reads `code` out of the JSON body and falls back to -1 when the body
    won't parse. Google's 5xx are served by the front end, before the API layer,
    as an HTML error page — so exactly the failures worth retrying arrive with
    `code == -1`.
    """
    status = getattr(getattr(exc, "response", None), "status_code", None)
    return status if isinstance(status, int) else exc.code


def _with_retry(op, attempts: int = _RETRY_ATTEMPTS, sleep=None):
    """Run a Sheets call, retrying transient API errors with exponential backoff.

    This bot answers a Telegram webhook: an unretried blip costs the user their
    forwarded link with nothing saved. See the module docstring for why the
    append itself is excluded.
    """
    _sleep = time.sleep if sleep is None else sleep
    for attempt in range(attempts):
        try:
            return op()
        except APIError as exc:
            if _status_of(exc) not in _TRANSIENT_CODES or attempt == attempts - 1:
                raise
            _sleep(_RETRY_BASE_DELAY_SECONDS * 2 ** attempt)


def lead_to_row(lead, row_id, now):
    """Build the positional sheet row for one lead (matches COLUMNS order)."""
    return [
        row_id,                  # id
        now,                     # Дата добавления
        lead.raw_text,           # Исходный текст
        lead.platform,           # Платформа
        lead.target,             # Источник
        lead.vacancy_context,    # Вакансия
        "",                      # Сообщение
        STATUS_NEW,              # Статус
        "",                      # Дата отправки
        lead.sheet_note(),       # Заметка (маршрут + оценка соответствия)
    ]


def _load_credentials(file_path: str, json_content: str) -> Credentials:
    """Local: load from a JSON file path. Cloud: load from JSON content (env var)."""
    if json_content.strip():
        return Credentials.from_service_account_info(json.loads(json_content), scopes=_SCOPES)
    if file_path.strip():
        return Credentials.from_service_account_file(file_path, scopes=_SCOPES)
    raise RuntimeError(
        "No Google credentials: set GOOGLE_SERVICE_ACCOUNT_JSON (cloud) "
        "or GOOGLE_SERVICE_ACCOUNT_FILE (local)."
    )


class SheetsRepo:
    def __init__(self, file_path: str, json_content: str, sheet_id: str, tab: str):
        client = gspread.authorize(_load_credentials(file_path, json_content))
        self._ws = client.open_by_key(sheet_id).worksheet(tab)

    def _ensure_header(self) -> None:
        first_row = _with_retry(lambda: self._ws.row_values(1))
        if first_row != COLUMNS:
            # (values, range_name) — gspread 5 took them the other way round, and
            # this call still had the old order. It only runs on a sheet whose
            # header is missing or renamed, i.e. first-time setup, which is why it
            # went unnoticed: every ordinary append skips it.
            _with_retry(lambda: self._ws.update([COLUMNS], "A1"))

    def _next_id(self) -> int:
        # number of data rows (excluding header) + 1
        values = _with_retry(lambda: self._ws.col_values(1))
        return max(len(values) - 1, 0) + 1

    def append_lead(self, lead: ExtractedLead) -> int:
        self._ensure_header()
        row_id = self._next_id()
        now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        row = lead_to_row(lead, row_id, now)
        # Deliberately NOT wrapped in _with_retry, and deliberately RAW — see the
        # module docstring for both.
        self._ws.append_row(row, value_input_option="RAW", table_range="A1")
        return row_id

    def count_by_status(self) -> dict[str, int]:
        """Tally leads by the 'Статус' column (excludes the header row)."""
        statuses = _with_retry(lambda: self._ws.col_values(_STATUS_COL))[1:]
        counts: dict[str, int] = {}
        for value in statuses:
            key = (value or "").strip()
            if not key:
                continue
            counts[key] = counts.get(key, 0) + 1
        return counts
