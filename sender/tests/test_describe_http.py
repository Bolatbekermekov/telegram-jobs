"""Общая дешёвая читалка описаний: чем она отвечает и когда молчит."""
import app.infrastructure.vacancy_fetcher as vf
from app.infrastructure.search.describe_http import http_vacancy_text


def test_returns_the_text_the_fetcher_read(monkeypatch):
    monkeypatch.setattr(vf, "fetch_vacancy_text", lambda url: "Frontend, удалённо")
    assert http_vacancy_text("https://hh.ru/vacancy/1") == "Frontend, удалённо"


def test_network_failure_reads_as_empty_not_as_a_crash(monkeypatch):
    """За пустотой стоит браузер; исключение отсюда обнулило бы всю площадку."""
    def boom(url):
        raise RuntimeError("нет сети")

    monkeypatch.setattr(vf, "fetch_vacancy_text", boom)
    assert http_vacancy_text("https://hh.ru/vacancy/2") == ""


def test_unknown_url_reads_as_empty():
    """Профиль человека читалка не знает — такие идут в браузер, как и раньше."""
    assert http_vacancy_text("https://www.linkedin.com/in/someone/") == ""
