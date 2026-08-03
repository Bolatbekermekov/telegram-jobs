"""Write path of SheetsRepo: atomicity, retries, and RAW input.

A write that fails *after* the message was already delivered is what leaves a
lead `new` and gets it sent to the same person again on the next run, so these
assert the exact shape of the API call — how many, which cells, which input
option — not merely that a call happened.
"""
import pytest
from gspread.utils import ValueInputOption, a1_range_to_grid_range, rowcol_to_a1

from app.domain.lead import (
    COL_DATE_SENT,
    COL_MESSAGE,
    COL_NOTE,
    COL_PLATFORM,
    COL_STATUS,
    COL_TARGET,
    COL_VACANCY,
    COLUMNS,
    STATUS_NEW,
    Lead,
)
from app.infrastructure import sheets_repo as sr
from app.infrastructure.sheets_repo import SheetsRepo, _with_retry


class _FakeResponse:
    """Minimal stand-in for the requests.Response gspread's APIError parses."""

    def __init__(self, code):
        self._code = code

    def json(self):
        return {"error": {"code": self._code, "message": "boom", "status": "X"}}


def _api_error(code):
    return sr.APIError(_FakeResponse(code))


class _HtmlResponse:
    """How Google actually answers a 5xx: an HTML page, not JSON.

    The failure is served by the front end, before the Sheets API layer, so there
    is no `{"error": {...}}` to parse. gspread catches the parse error and falls
    back to `code = -1` (gspread/exceptions.py), which is why keying the retry on
    `exc.code` alone never retried the most common outage there is.
    """

    def __init__(self, status_code=502):
        self.status_code = status_code
        self.text = ("<!DOCTYPE html><title>Error {} (Server Error)!!1</title>"
                     .format(status_code))

    def json(self):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")


def _api_error_html(status_code=502):
    return sr.APIError(_HtmlResponse(status_code))


class _FakeWorksheet:
    """Records writes; fails the first `fail_times` calls with `code`.

    `error` overrides the raised exception, for the HTML-bodied 5xx that carries
    no parseable code.
    """

    def __init__(self, fail_times=0, code=429, error=None):
        self.updates = []
        self.batches = []
        self.calls = 0
        self._fail_times = fail_times
        self._code = code
        self._error = error

    def _maybe_fail(self):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise self._error() if self._error else _api_error(self._code)

    def update(self, values, range_name=None, **kw):
        self._maybe_fail()
        self.updates.append((values, range_name, kw))

    def batch_update(self, data, **kw):
        self._maybe_fail()
        self.batches.append((data, kw))


class _Lead:
    row = 7


def _repo(ws):
    """A repo bound to a fake sheet — __init__ would authorize over the network."""
    repo = SheetsRepo.__new__(SheetsRepo)
    repo._ws = ws
    return repo


def _lead(row=2, platform="threads",
          target="https://www.threads.com/@lnkrnchk/post/DbL4LxBl6v9"):
    """A real Lead: update_resolved rewrites its row, so the fields matter."""
    return Lead(row=row, lead_id="7", platform=platform, target=target,
                vacancy_context="короткий текст", raw_text=target,
                status=STATUS_NEW)


@pytest.fixture
def fake_ws_repo():
    ws = _FakeWorksheet()
    return _repo(ws), ws


# --- the assumption the ranged write rests on -------------------------------

def test_message_status_and_date_columns_stay_adjacent():
    """mark_sent writes one span; reordering COLUMNS would corrupt other cells."""
    assert (COL_STATUS, COL_DATE_SENT) == (COL_MESSAGE + 1, COL_MESSAGE + 2)


# --- mark_sent --------------------------------------------------------------

def test_mark_sent_writes_message_status_and_date_in_a_single_call():
    ws = _FakeWorksheet()
    _repo(ws).mark_sent(_Lead(), "тело письма", "sent")

    assert ws.calls == 1
    (values, cells, _), = ws.updates
    assert cells == "G7:I7"
    assert values[0][0] == "тело письма"
    assert values[0][1] == "sent"


def test_mark_sent_stores_a_leading_equals_as_text_not_a_formula():
    """The body is model-generated from a scraped vacancy — never evaluate it."""
    ws = _FakeWorksheet()
    _repo(ws).mark_sent(_Lead(), '=IMAGE("https://evil.tld")', "sent")

    (_, _, kw), = ws.updates
    assert kw["value_input_option"] == ValueInputOption.raw


def test_mark_sent_retries_a_quota_error_then_succeeds(monkeypatch):
    monkeypatch.setattr(sr.time, "sleep", lambda _s: None)
    ws = _FakeWorksheet(fail_times=2, code=429)

    _repo(ws).mark_sent(_Lead(), "body", "sent")

    assert ws.calls == 3
    assert len(ws.updates) == 1


def test_mark_sent_raises_after_the_last_attempt(monkeypatch):
    monkeypatch.setattr(sr.time, "sleep", lambda _s: None)
    ws = _FakeWorksheet(fail_times=99, code=429)

    with pytest.raises(sr.APIError):
        _repo(ws).mark_sent(_Lead(), "body", "sent")

    assert ws.calls == 3
    assert ws.updates == []


def test_gspread_reports_an_html_5xx_as_code_minus_one():
    """Pins the mechanism the retry has to survive, not our own code."""
    assert _api_error_html(502).code == -1


def test_mark_sent_retries_an_html_502_then_succeeds(monkeypatch):
    """A 502 arrives as HTML, so `exc.code` is -1 — retry on the HTTP status.

    This is the write that had already delivered a Telegram message when it blew
    up: no retry meant the run died with the lead still `new`, and the next run
    messaged the same person a second time.
    """
    monkeypatch.setattr(sr.time, "sleep", lambda _s: None)
    ws = _FakeWorksheet(fail_times=2, error=lambda: _api_error_html(502))

    _repo(ws).mark_sent(_Lead(), "body", "sent")

    assert ws.calls == 3
    assert len(ws.updates) == 1


def test_mark_sent_does_not_retry_an_html_400(monkeypatch):
    """A bad range is our bug — an unparseable body must not turn it into a retry."""
    monkeypatch.setattr(sr.time, "sleep", lambda _s: None)
    ws = _FakeWorksheet(fail_times=99, error=lambda: _api_error_html(400))

    with pytest.raises(sr.APIError):
        _repo(ws).mark_sent(_Lead(), "body", "sent")

    assert ws.calls == 1


def test_mark_status_retries_an_html_502_then_succeeds(monkeypatch):
    monkeypatch.setattr(sr.time, "sleep", lambda _s: None)
    ws = _FakeWorksheet(fail_times=2, error=lambda: _api_error_html(503))

    _repo(ws).mark_status(_Lead(), "manual", note="n")

    assert ws.calls == 3
    assert len(ws.batches) == 1


def test_mark_sent_does_not_retry_a_permission_error():
    """403 means the sheet isn't shared with the service account — retrying hides it."""
    ws = _FakeWorksheet(fail_times=99, code=403)

    with pytest.raises(sr.APIError):
        _repo(ws).mark_sent(_Lead(), "body", "sent")

    assert ws.calls == 1


# --- update_vacancy ---------------------------------------------------------

def test_update_vacancy_writes_only_the_vacancy_cell():
    ws = _FakeWorksheet()
    _repo(ws).update_vacancy(_Lead(), "Backend Engineer, Алматы, гибрид")

    (values, cells, kw), = ws.updates
    assert cells == "F7"
    assert values == [["Backend Engineer, Алматы, гибрид"]]
    assert kw["value_input_option"] == ValueInputOption.raw


def test_update_vacancy_never_touches_status():
    """The lead stays `new` — it is generated and delivered later in the same run."""
    ws = _FakeWorksheet()
    _repo(ws).update_vacancy(_Lead(), "текст вакансии")

    (_, cells, _), = ws.updates
    grid = a1_range_to_grid_range(cells)
    status_index = COL_STATUS - 1
    assert not (grid["startColumnIndex"] <= status_index < grid["endColumnIndex"]), (
        f"{cells} covers the Статус column")


# --- mark_status ------------------------------------------------------------

def test_mark_status_writes_status_and_note_in_a_single_call():
    ws = _FakeWorksheet()
    _repo(ws).mark_status(_Lead(), "manual", note="gated form")

    assert ws.calls == 1
    (data, kw), = ws.batches
    assert [d["range"] for d in data] == ["H7", "J7"]
    assert [d["values"] for d in data] == [[["manual"]], [["gated form"]]]
    assert kw["value_input_option"] == ValueInputOption.raw


def test_mark_status_without_a_note_touches_only_the_status_cell():
    ws = _FakeWorksheet()
    _repo(ws).mark_status(_Lead(), "skipped")

    (data, _), = ws.batches
    assert [d["range"] for d in data] == ["H7"]


def test_mark_status_refuses_to_park_a_lead_as_invited():
    """`invited` без даты теперь означает «закрыть на следующем прогоне», так что
    поставить его write-ом, который дату не пишет, — значит тихо убить лид.
    Единственный правильный путь — mark_invited; пусть это будет невозможно
    сделать неправильно, а не просто описано в комментарии."""
    from app.domain.lead import STATUS_INVITED
    ws = _FakeWorksheet()
    with pytest.raises(ValueError):
        _repo(ws).mark_status(_Lead(), STATUS_INVITED, note="лимит приглашений")
    assert ws.calls == 0


def test_mark_status_never_blanks_the_sent_date():
    """Статус and Заметка straddle Дата отправки — one span would wipe it."""
    ws = _FakeWorksheet()
    _repo(ws).mark_status(_Lead(), "failed", note="boom")

    (data, _), = ws.batches
    assert rowcol_to_a1(_Lead.row, COL_DATE_SENT) not in {d["range"] for d in data}


# --- mark_invited -----------------------------------------------------------
#
# Запрос на контакт — тоже обращение к человеку, и его дата решает, когда
# перестать ждать ответа. `mark_status` её не пишет, поэтому все 7 строк
# `invited` в листе на 2026-08-03 остались без даты, а срок давности стало не
# от чего считать.

def test_status_date_and_note_are_adjacent():
    """mark_invited пишет их одним диапазоном; перестановка COLUMNS его порвёт."""
    assert (COL_DATE_SENT, COL_NOTE) == (COL_STATUS + 1, COL_STATUS + 2)


def test_mark_invited_writes_status_date_and_note_in_a_single_call():
    ws = _FakeWorksheet()
    _repo(ws).mark_invited(_Lead(), note="лимит персональных приглашений")

    assert ws.calls == 1
    (values, cells, kw), = ws.updates
    assert cells == "H7:J7"
    assert values[0][0] == "invited"
    assert values[0][2] == "лимит персональных приглашений"
    assert kw["value_input_option"] == ValueInputOption.raw


def test_mark_invited_stamps_a_date_the_sender_can_read_back():
    """Дата обязана быть в том же формате, что пишет mark_sent, — иначе
    `_parse_sent_at` её не разберёт и приглашение будет считаться безвозрастным.
    """
    ws = _FakeWorksheet()
    _repo(ws).mark_invited(_Lead(), note="n")

    (values, _, _), = ws.updates
    assert sr._parse_sent_at(values[0][1]) is not None


def test_mark_invited_never_touches_the_message_column():
    """Письма не было — колонка «Сообщение» должна остаться пустой, иначе лист
    утверждает, что рекрутёр получил текст, которого никто не получал."""
    ws = _FakeWorksheet()
    _repo(ws).mark_invited(_Lead(), note="n")

    (_, cells, _), = ws.updates
    grid = a1_range_to_grid_range(cells)
    assert not (grid["startColumnIndex"] <= COL_MESSAGE - 1 < grid["endColumnIndex"])


# --- the retry helper itself ------------------------------------------------

def test_with_retry_backs_off_exponentially():
    slept, calls = [], []

    def op():
        calls.append(1)
        raise _api_error(429)

    with pytest.raises(sr.APIError):
        _with_retry(op, attempts=4, sleep=slept.append)

    assert len(calls) == 4
    assert slept == [1.0, 2.0, 4.0]


def test_with_retry_returns_the_result_without_sleeping():
    slept = []
    assert _with_retry(lambda: "ok", sleep=slept.append) == "ok"
    assert slept == []


# --- resolved threads leads -------------------------------------------------

def test_lead_column_indexes_match_the_header():
    assert COLUMNS[COL_PLATFORM - 1] == "Платформа"
    assert COLUMNS[COL_TARGET - 1] == "Источник"
    assert COLUMNS[COL_VACANCY - 1] == "Вакансия"


def test_platform_target_and_vacancy_are_adjacent():
    """update_resolved writes them as ONE span; if a column is ever inserted
    between them that span would silently overwrite the wrong cell."""
    assert COL_TARGET == COL_PLATFORM + 1
    assert COL_VACANCY == COL_TARGET + 1


def test_update_resolved_writes_the_row_in_one_batch(fake_ws_repo):
    """A threads lead becomes a telegram lead: platform, target and vacancy
    text must land together or not at all — a half-applied rewrite would leave
    the lead pointing at a Threads URL with a Telegram platform."""
    repo, ws = fake_ws_repo
    lead = _lead(row=5)

    repo.update_resolved(lead, "telegram", "@skyluckwalker",
                         "Ищу Full Stack Developer", note="резолв из Threads")

    assert ws.calls == 1, "должна быть одна операция записи"
    (data, kw), = ws.batches
    assert [d["range"] for d in data] == ["D5:F5", "J5"]
    assert [d["values"] for d in data] == [
        [["telegram", "@skyluckwalker", "Ищу Full Stack Developer"]],
        [["резолв из Threads"]],
    ]
    assert kw["value_input_option"] == ValueInputOption.raw


def test_update_resolved_without_a_note_writes_only_the_span(fake_ws_repo):
    repo, ws = fake_ws_repo
    repo.update_resolved(_lead(row=5), "telegram", "@x", "текст")

    (data, _), = ws.batches
    assert [d["range"] for d in data] == ["D5:F5"]


def test_update_resolved_never_touches_status(fake_ws_repo):
    """The lead stays `new` — it has not been sent yet, so no written range may
    cover Статус, not even as part of a wider span."""
    repo, ws = fake_ws_repo
    repo.update_resolved(_lead(row=5), "telegram", "@x", "текст", note="n")

    (data, _), = ws.batches
    status = COL_STATUS - 1                      # grid ranges are 0-based
    for d in data:
        span = a1_range_to_grid_range(d["range"])
        assert not (span["startColumnIndex"] <= status
                    < span["endColumnIndex"]), d["range"]
