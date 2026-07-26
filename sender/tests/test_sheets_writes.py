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


class _FakeWorksheet:
    """Records writes; fails the first `fail_times` calls with `code`."""

    def __init__(self, fail_times=0, code=429):
        self.updates = []
        self.batches = []
        self.calls = 0
        self._fail_times = fail_times
        self._code = code

    def _maybe_fail(self):
        self.calls += 1
        if self.calls <= self._fail_times:
            raise _api_error(self._code)

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


def test_mark_sent_does_not_retry_a_permission_error():
    """403 means the sheet isn't shared with the service account — retrying hides it."""
    ws = _FakeWorksheet(fail_times=99, code=403)

    with pytest.raises(sr.APIError):
        _repo(ws).mark_sent(_Lead(), "body", "sent")

    assert ws.calls == 1


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


def test_mark_status_never_blanks_the_sent_date():
    """Статус and Заметка straddle Дата отправки — one span would wipe it."""
    ws = _FakeWorksheet()
    _repo(ws).mark_status(_Lead(), "failed", note="boom")

    (data, _), = ws.batches
    assert rowcol_to_a1(_Lead.row, COL_DATE_SENT) not in {d["range"] for d in data}


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
