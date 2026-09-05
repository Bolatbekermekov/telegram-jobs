"""Чтение листа переживает короткий сбой сети; запись — по-прежнему нет.

Живьём 2026-09-05: `get_all_records` подвис на `sheets.googleapis.com` и упал
с `requests.exceptions.ReadTimeout` (read timeout=None — то есть ждал вечно).
Прогон умер трейсбеком посреди очереди, 66 лидов остались необработанными.

`_with_retry` не помог бы и на записи: он ловит только `APIError`, а таймаут
это другое исключение.

Разница между чтением и записью не в том, стоит ли повторять, а в ЦЕНЕ ОШИБКИ:
повтор записи после дошедшего запроса создаёт дубль строки — дубль лида и дубль
отклика; повтор чтения не создаёт ничего.
"""
import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import ReadTimeout

from app.infrastructure import sheets_repo as sr


def test_a_timeout_is_retried_and_the_read_succeeds():
    calls = []

    def op():
        calls.append(1)
        if len(calls) < 3:
            raise ReadTimeout("Read timed out")
        return ["данные"]

    assert sr._read_with_retry(op, sleep=lambda s: None) == ["данные"]
    assert len(calls) == 3


def test_a_connection_error_is_retried_too():
    calls = []

    def op():
        calls.append(1)
        if len(calls) < 2:
            raise RequestsConnectionError("boom")
        return []

    assert sr._read_with_retry(op, sleep=lambda s: None) == []


def test_the_last_attempt_still_raises():
    """Молчать о сбое нельзя: пустой список прочитался бы как «лидов нет»,
    и прогон тихо ничего бы не отправил."""
    def op():
        raise ReadTimeout("Read timed out")

    with pytest.raises(ReadTimeout):
        sr._read_with_retry(op, attempts=3, sleep=lambda s: None)


def test_it_waits_longer_after_each_failure():
    waits = []

    calls = []

    def op():
        calls.append(1)
        if len(calls) < 3:
            raise ReadTimeout("x")
        return "ok"

    sr._read_with_retry(op, sleep=waits.append)
    assert waits == sorted(waits) and len(set(waits)) == len(waits)


def test_the_client_gets_a_bounded_timeout(monkeypatch):
    """Без него чтение уходит в `read timeout=None` и ждёт вечно."""
    seen = {}

    class _Client:
        def set_timeout(self, t):
            seen["timeout"] = t

        def open_by_key(self, key):
            class _S:
                def worksheet(self, tab):
                    return object()
            return _S()

    monkeypatch.setattr(sr, "_load_credentials", lambda p: None)
    monkeypatch.setattr(sr.gspread, "authorize", lambda creds: _Client())
    sr.SheetsRepo("cred.json", "sheet", "Лист1")

    assert isinstance(seen.get("timeout"), (int, float))
    assert 0 < seen["timeout"] <= 300
