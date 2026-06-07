"""Google Sheets repository (gspread). Appends new leads with status=new."""
import datetime as _dt
import json

import gspread
from google.oauth2.service_account import Credentials

from app.domain.lead import COLUMNS, STATUS_NEW, ExtractedLead

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
_STATUS_COL = COLUMNS.index("Статус") + 1  # 1-based column number


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
        first_row = self._ws.row_values(1)
        if first_row != COLUMNS:
            self._ws.update("A1", [COLUMNS])

    def _next_id(self) -> int:
        # number of data rows (excluding header) + 1
        return max(len(self._ws.col_values(1)) - 1, 0) + 1

    def append_lead(self, lead: ExtractedLead) -> int:
        self._ensure_header()
        row_id = self._next_id()
        now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        row = [
            row_id,                  # id
            now,                     # Дата добавления
            lead.raw_text,           # Исходный текст
            lead.nickname,           # Ник/ссылка
            lead.vacancy_context,    # Вакансия
            "",                      # Сообщение
            STATUS_NEW,              # Статус
            "",                      # Дата отправки
            "",                      # Заметка
        ]
        self._ws.append_row(row, value_input_option="USER_ENTERED")
        return row_id

    def count_by_status(self) -> dict[str, int]:
        """Tally leads by the 'Статус' column (excludes the header row)."""
        statuses = self._ws.col_values(_STATUS_COL)[1:]
        counts: dict[str, int] = {}
        for value in statuses:
            key = (value or "").strip()
            if not key:
                continue
            counts[key] = counts.get(key, 0) + 1
        return counts
