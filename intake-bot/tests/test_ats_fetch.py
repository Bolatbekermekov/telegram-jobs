"""Страница ATS читается тем же фетчером, что hh и агрегаторы.

Раньше её хвост диспетчера отбрасывал молча: неизвестный хост — `return ""`, без
ошибки и без следа. Лид сохранялся бы с пустой «Вакансией», а письмо писалось бы
из одной строки нашей же оценки — ровно тот дефект, который чинили 2026-09-11.
"""
from app.infrastructure import vacancy_fetcher as vf

JOB = "https://boards.greenhouse.io/block/jobs/5406229008"
PAGE = """<!doctype html><html><head>
<script type="application/ld+json">
{"@type":"JobPosting","title":"Senior Go Engineer",
 "description":"<p>Build gateways in Go. 5+ years required.</p>"}
</script></head><body><div id="root"></div></body></html>"""


def test_an_ats_vacancy_is_read(monkeypatch):
    monkeypatch.setattr(vf, "_get", lambda url, timeout, ua=None: PAGE)
    assert "Build gateways in Go." in vf.fetch_vacancy_text(JOB)


def test_the_url_asked_for_is_the_url_fetched(monkeypatch):
    """Никаких подстановок: открываем ровно то, что прислал человек."""
    seen = []
    monkeypatch.setattr(vf, "_get",
                        lambda url, timeout, ua=None: seen.append(url) or PAGE)
    vf.fetch_vacancy_text(JOB)
    assert seen == [JOB]


def test_a_page_that_is_not_a_vacancy_is_still_refused(monkeypatch):
    """Доска целиком — не вакансия, и сеть ради неё не трогается."""
    monkeypatch.setattr(vf, "_get", lambda *a, **k: PAGE)
    assert vf.fetch_vacancy_text("https://boards.greenhouse.io/block") == ""
