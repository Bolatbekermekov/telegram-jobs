"""Поиск открывает таблицу с тем же таймаутом, что и отправка.

Живьём 2026-09-15 (поиск AI Engineer по всем площадкам): LinkedIn собрал 165
карточек, и процесс час простоял без процессора с открытым соединением к Google.
`run_search_once` и воркер открывали таблицу через `gspread.authorize` без
таймаута, и подвисший запрос ждал вечно. У отправки таймаут стоит с 2026-09-05
(`SheetsRepo`), у поиска его не было.
"""
import pytest
from requests.exceptions import ReadTimeout

from app.domain.candidate import normalize_url
from app.infrastructure import sheets_repo as sr
from app.infrastructure.search_leads_repo import SearchLeadsRepo


class _Client:
    def __init__(self):
        self.calls = []

    def set_timeout(self, seconds):
        self.calls.append(("timeout", seconds))

    def open_by_key(self, key):
        self.calls.append(("open", key))
        return "book"


def test_the_sheet_is_opened_with_a_timeout(monkeypatch):
    client = _Client()
    monkeypatch.setattr(sr, "_load_credentials", lambda path: "creds")
    monkeypatch.setattr(sr.gspread, "authorize", lambda creds: client)

    assert sr.open_book("sa.json", "sheet-id") == "book"
    assert client.calls == [("timeout", sr._HTTP_TIMEOUT_SECONDS), ("open", "sheet-id")]


def test_the_one_shot_search_opens_the_sheet_through_it(monkeypatch):
    import gspread

    from app.interface import cli

    class Opened(Exception):
        pass

    def without_timeout(*args, **kwargs):
        raise AssertionError("таблица открыта мимо open_book — без таймаута")

    def through_helper(path, sheet_id):
        raise Opened()

    monkeypatch.setattr(gspread, "authorize", without_timeout)
    monkeypatch.setattr(sr, "open_book", through_helper)

    with pytest.raises(Opened):
        cli.run_search_once(["remotive"])


class _Sheet:
    def __init__(self, values):
        self.values, self.calls = values, 0

    def col_values(self, col):
        self.calls += 1
        if self.calls == 1:
            raise ReadTimeout("Read timed out")
        return self.values


def test_known_urls_survive_a_read_timeout(monkeypatch):
    monkeypatch.setattr(sr.time, "sleep", lambda seconds: None)
    link = "https://www.indeed.com/rc/clk?jk=ed6a7fc3bedd441c&bb=x"
    repo = SearchLeadsRepo(_Sheet(["Источник", link]), None, cap=10)

    assert repo.known_urls() == {normalize_url(link)}
