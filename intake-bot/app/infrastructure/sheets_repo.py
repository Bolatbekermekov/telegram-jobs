"""Google Sheets repository (gspread). Appends new leads with status=new."""
import datetime as _dt

import gspread
from google.oauth2.service_account import Credentials

from app.domain.lead import COLUMNS, STATUS_NEW, ExtractedLead

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _load_credentials(service_account_path: str) -> Credentials:
    """Load service-account credentials from a JSON file path."""
    return Credentials.from_service_account_file(service_account_path, scopes=_SCOPES)


class SheetsRepo:
    def __init__(self, service_account_path: str, sheet_id: str, tab: str):
        client = gspread.authorize(_load_credentials(service_account_path))
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
