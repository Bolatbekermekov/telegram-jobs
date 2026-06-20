"""Intake-side view of the «Кандидаты» tab: render, parse taps, promote to main.

Pure helpers (message/buttons, callback parsing, row mapping) are unit-tested;
the CandidatesGateway class composes them over gspread worksheets.
"""
from app.domain.lead import COLUMNS, STATUS_NEW

CANDIDATE_COLUMNS = [
    "id", "Платформа", "Тип", "URL", "Title", "Company",
    "Salary", "Location", "Summary", "Статус", "Дата",
]

_BADGE = {"linkedin": "🔵 LinkedIn", "wellfound": "🅰️ Wellfound"}


def _col(row, name):
    return row[CANDIDATE_COLUMNS.index(name)]


def parse_callback(data: str):
    action, _, cid = data.partition(":")
    return action, cid


_VERDICT = {"approve": "✅ Взято", "skip": "❌ Скип"}


def decided_text(original_text: str, action: str) -> str:
    """Card text with a verdict line appended (caller removes the buttons)."""
    return f"{original_text}\n\n{_VERDICT.get(action, action)}"


def build_vacancy_message(row):
    platform = _col(row, "Платформа")
    kind = _col(row, "Тип")
    badge = _BADGE.get(platform, platform)
    title = _col(row, "Title")
    company = _col(row, "Company")
    salary = _col(row, "Salary") or "—"
    location = _col(row, "Location") or "—"
    summary = _col(row, "Summary")
    cid = _col(row, "id")
    text = (
        f"{badge} · {kind}\n"
        f"{title} — {company}\n"
        f"💰 {salary} · 📍 {location}\n"
        f"📝 {summary}\n{_col(row, 'URL')}"
    )
    buttons = [[
        {"text": "✅ Approve", "callback_data": f"approve:{cid}"},
        {"text": "❌ Not", "callback_data": f"skip:{cid}"},
    ]]
    return text, buttons


def candidate_row_to_lead_row(row, row_id, now: str) -> list:
    """Map a «Кандидаты» row to a positional main-tab lead row (status=new)."""
    title = _col(row, "Title")
    summary = _col(row, "Summary")
    vacancy = f"{title} — {summary}".strip(" —")
    values = {
        "id": row_id,
        "Дата добавления": now,
        "Исходный текст": vacancy,
        "Платформа": _col(row, "Платформа"),
        "Источник": _col(row, "URL"),
        "Вакансия": vacancy,
        "Сообщение": "",
        "Статус": STATUS_NEW,
        "Дата отправки": "",
        "Заметка": "",
    }
    return [values[c] for c in COLUMNS]


class CandidatesGateway:
    def __init__(self, candidates_ws, main_ws):
        self._cand = candidates_ws
        self._main = main_ws

    def pending(self, limit: int):
        rows = self._cand.get_all_values()[1:]
        return [r for r in rows if len(r) >= 10 and _col(r, "Статус") == "pending"][:limit]

    def _find_row_index(self, cid: str):
        ids = self._cand.col_values(1)
        for i, val in enumerate(ids[1:], start=2):
            if val == cid:
                return i
        return None

    def _get_row(self, cid: str):
        idx = self._find_row_index(cid)
        return (idx, self._cand.row_values(idx)) if idx else (None, None)

    def approve(self, cid: str) -> bool:
        idx, row = self._get_row(cid)
        if idx is None or _col(row, "Статус") != "pending":
            return False  # idempotent: already handled / missing
        import datetime as _dt
        row_id = max(len(self._main.col_values(1)) - 1, 0) + 1
        now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        self._main.append_row(candidate_row_to_lead_row(row, row_id, now),
                              value_input_option="USER_ENTERED")
        self._cand.update_cell(idx, CANDIDATE_COLUMNS.index("Статус") + 1, "taken")
        return True

    def reject(self, cid: str) -> bool:
        idx, row = self._get_row(cid)
        if idx is None or _col(row, "Статус") != "pending":
            return False
        self._cand.update_cell(idx, CANDIDATE_COLUMNS.index("Статус") + 1, "rejected")
        return True
