"""Google Sheets repository for the sender: read `new` leads, update status."""
import datetime as _dt

import gspread
from google.oauth2.service_account import Credentials

from app.domain.lead import (
    COL_DATE_SENT,
    COL_MESSAGE,
    COL_STATUS,
    COLUMNS,
    STATUS_NEW,
    Lead,
)

_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


def _load_credentials(service_account_path: str) -> Credentials:
    """Load service-account credentials from a JSON file path."""
    return Credentials.from_service_account_file(service_account_path, scopes=_SCOPES)


class SheetsRepo:
    def __init__(self, service_account_path: str, sheet_id: str, tab: str):
        client = gspread.authorize(_load_credentials(service_account_path))
        self._ws = client.open_by_key(sheet_id).worksheet(tab)

    def fetch_new_leads(self) -> list[Lead]:
        records = self._ws.get_all_records(expected_headers=COLUMNS)
        leads: list[Lead] = []
        for offset, rec in enumerate(records):
            if str(rec.get("Статус", "")).strip() == STATUS_NEW:
                leads.append(
                    Lead(
                        row=offset + 2,  # +1 header, +1 to 1-based
                        lead_id=str(rec.get("id", "")),
                        nickname=str(rec.get("Ник/ссылка", "")).strip(),
                        vacancy_context=str(rec.get("Вакансия", "")).strip(),
                        raw_text=str(rec.get("Исходный текст", "")).strip(),
                        status=STATUS_NEW,
                    )
                )
        return leads

    def mark_sent(self, lead: Lead, message: str, status: str) -> None:
        now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        self._ws.update_cell(lead.row, COL_MESSAGE, message)
        self._ws.update_cell(lead.row, COL_STATUS, status)
        self._ws.update_cell(lead.row, COL_DATE_SENT, now)

    def mark_status(self, lead: Lead, status: str) -> None:
        self._ws.update_cell(lead.row, COL_STATUS, status)
