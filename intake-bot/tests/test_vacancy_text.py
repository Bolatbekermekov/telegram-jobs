"""Deciding a message has no vacancy text, and pulling one out of hh HTML."""
from app.domain.vacancy_text import extract_hh_vacancy, is_link_only

IOS_SHARE = ("Vacancy: https://hh.kz/vacancy/135171273?from=share_ios\n\n"
             "Sent via hh mobile app https://hh.ru/mobile?from=share_ios")


# --- is_link_only -----------------------------------------------------------

def test_ios_share_counts_as_link_only():
    """The exact shape the phone sends — nothing here to summarise."""
    assert is_link_only(IOS_SHARE)


def test_a_bare_url_counts_as_link_only():
    assert is_link_only("https://hh.ru/vacancy/135171273")


def test_a_pasted_description_does_not():
    text = ("Ищем Middle QA Engineer в финтех. Обязанности: функциональное и "
            "регрессионное тестирование, написание тест-кейсов, работа с баг-трекингом. "
            "Требования: опыт от 2 лет, REST API, знание методологий тестирования.")
    assert not is_link_only(text)


def test_a_description_with_a_link_does_not():
    text = ("Senior frontend в IREV, удалёнка. React и TypeScript, желательно "
            "ClojureScript. Английский для международной команды. Оформление по "
            "контракту, зарплата в долларах. Подробности: https://hh.ru/vacancy/1")
    assert not is_link_only(text)


def test_empty_text_counts_as_link_only():
    assert is_link_only("")


# --- extract_hh_vacancy -----------------------------------------------------

_HTML = """
<html><body>
<h1 data-qa="vacancy-title">Специалист по внедрению ИИ</h1>
<span data-qa="vacancy-salary-compensation-type-net">от 500 000 ₸ на руки</span>
<div data-qa="vacancy-description"><p>Мы — Tier IV дата-центр.</p>
<script>window.x = 1;</script>
<ul><li>Автоматизируем процессы с помощью AI</li></ul></div>
<div data-qa="vacancy-view-employment-mode">полный день</div>
</body></html>
"""


def test_title_salary_and_body_are_extracted():
    out = extract_hh_vacancy(_HTML)
    assert "Специалист по внедрению ИИ" in out
    assert "500 000" in out
    assert "Tier IV дата-центр" in out
    assert "Автоматизируем процессы" in out


def test_markup_and_scripts_are_stripped():
    out = extract_hh_vacancy(_HTML)
    assert "<" not in out and ">" not in out
    assert "window.x" not in out


def test_the_next_block_is_not_swallowed():
    """The description regex stops at the following data-qa block."""
    assert "полный день" not in extract_hh_vacancy(_HTML)


def test_html_without_a_description_yields_nothing():
    assert extract_hh_vacancy("<html><body>404</body></html>") == ""


def test_empty_html_yields_nothing():
    assert extract_hh_vacancy("") == ""


def test_output_is_capped():
    html = ('<div data-qa="vacancy-description">' + ("текст " * 5000)
            + '</div><div data-qa="next">')
    assert len(extract_hh_vacancy(html, max_chars=500)) <= 700   # body cap + title line


def test_html_entities_are_decoded():
    """hh writes "Support &amp; QA"; the raw entity would reach the summary prompt."""
    html = ('<h1 data-qa="vacancy-title">Support &amp; QA</h1>'
            '<div data-qa="vacancy-description">Опыт &gt; 2 лет, зарплата &lt; рынка,'
            ' &quot;гибкий&quot; график</div><div data-qa="next">')
    out = extract_hh_vacancy(html)
    assert "Support & QA" in out
    assert "Опыт > 2 лет" in out
    assert "&amp;" not in out and "&gt;" not in out


# --- LinkedIn job pages -----------------------------------------------------

_LI_HTML = """
<html><body>
<h1 class="top-card-layout__title">Chatbot Developer (WhatsApp, Telegram)</h1>
<a class="topcard__org-name-link" href="#">Mindrift</a>
<div class="show-more-less-html__markup"><p>Mindrift is looking for skilled Bot
Developers to build conversational bots.</p><script>var a=1;</script></div>
</body></html>
"""


def test_linkedin_title_company_and_body_are_extracted():
    from app.domain.vacancy_text import extract_linkedin_vacancy

    out = extract_linkedin_vacancy(_LI_HTML)
    assert "Chatbot Developer" in out
    assert "Mindrift" in out
    assert "conversational bots" in out
    assert "var a=1" not in out and "<" not in out


def test_linkedin_html_without_a_description_yields_nothing():
    from app.domain.vacancy_text import extract_linkedin_vacancy

    assert extract_linkedin_vacancy("<html><body>authwall</body></html>") == ""


def test_a_short_but_real_posting_is_not_link_only():
    """91 chars of real text — the old 120 threshold called this a bare link."""
    assert not is_link_only(
        "Sarvottam Solutions is hiring Junior AI Engineer\n\nFor 2024, 2025 grads\n"
        "Location: Ahemdabad\n\nhttps://www.linkedin.com/jobs/view/4438796193/")


# --- fetch retry ------------------------------------------------------------

class _FakeResp:
    def __init__(self, status, text=""):
        self.status_code = status
        self.text = text


def _patched_httpx(monkeypatch, responses):
    """Feed _get a queue of responses (or exceptions) and count the calls."""
    import types
    calls = []
    queue = list(responses)

    def _get(url, **kw):
        calls.append(url)
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(get=_get))
    return calls


import sys  # noqa: E402

from app.infrastructure import vacancy_fetcher as vf  # noqa: E402


def test_throttled_first_attempt_is_retried(monkeypatch):
    """A burst of backfill requests gets throttled; the page is fine a moment later."""
    calls = _patched_httpx(monkeypatch, [_FakeResp(429), _FakeResp(200, "<ok>")])
    assert vf._get("https://hh.ru/vacancy/1", 8.0, sleep=lambda _s: None) == "<ok>"
    assert len(calls) == 2


def test_a_network_error_is_retried(monkeypatch):
    calls = _patched_httpx(monkeypatch, [OSError("reset"), _FakeResp(200, "<ok>")])
    assert vf._get("https://hh.ru/vacancy/1", 8.0, sleep=lambda _s: None) == "<ok>"
    assert len(calls) == 2


def test_a_restricted_page_is_not_retried(monkeypatch):
    """403 is the site's final answer — retrying only waits longer for nothing."""
    calls = _patched_httpx(monkeypatch, [_FakeResp(403)])
    assert vf._get("https://hh.ru/vacancy/1", 8.0, sleep=lambda _s: None) == ""
    assert len(calls) == 1


def test_a_removed_page_is_not_retried(monkeypatch):
    calls = _patched_httpx(monkeypatch, [_FakeResp(404)])
    assert vf._get("https://linkedin.com/jobs/view/1", 8.0, sleep=lambda _s: None) == ""
    assert len(calls) == 1


def test_it_gives_up_after_the_last_attempt(monkeypatch):
    calls = _patched_httpx(monkeypatch, [_FakeResp(429), _FakeResp(429)])
    assert vf._get("https://hh.ru/vacancy/1", 8.0, sleep=lambda _s: None) == ""
    assert len(calls) == 2


def test_the_timeout_stays_under_a_serverless_budget():
    """A fetch that outlives the function turns a saved lead into a killed request."""
    assert vf._TIMEOUT_SECONDS <= 10
