"""Threads is fetched with a NON-browser User-Agent. This is the opposite of hh and
LinkedIn, and getting it wrong returns an empty JS shell — so it is pinned by test."""
from pathlib import Path

import app.infrastructure.vacancy_fetcher as vf

_FX = Path(__file__).parent / "fixtures" / "threads"


def test_recognises_threads_post_urls():
    assert vf.is_threads_post_url("https://www.threads.com/@a/post/DbL4LxBl6v9")
    assert vf.is_threads_post_url("https://threads.net/@a.b/post/Xy-1")
    assert not vf.is_threads_post_url("https://www.threads.com/@a")
    assert not vf.is_threads_post_url("https://hh.ru/vacancy/1")


def test_threads_posts_are_fetchable():
    assert vf.is_fetchable_vacancy_url("https://www.threads.com/@a/post/Db1")


def test_threads_is_fetched_without_the_browser_user_agent(monkeypatch):
    seen = {}

    def fake_get(url, timeout, attempts=2, sleep=None, ua=None):
        seen["ua"] = ua
        return (_FX / "post.html").read_text(encoding="utf-8")

    monkeypatch.setattr(vf, "_get", fake_get)
    text = vf.fetch_vacancy_text("https://www.threads.com/@lnkrnchk/post/DbL4LxBl6v9")

    assert text.startswith("Ищу Full Stack Developer")
    assert seen["ua"] == vf._CLIENT_UA
    assert "Mozilla" not in seen["ua"], "браузерный UA отдаёт пустой SPA-скелет"


def test_hh_and_linkedin_keep_the_browser_user_agent(monkeypatch):
    seen = []
    monkeypatch.setattr(vf, "_get",
                        lambda url, timeout, attempts=2, sleep=None, ua=None:
                        seen.append(ua) or "")
    vf.fetch_vacancy_text("https://hh.ru/vacancy/1")
    vf.fetch_vacancy_text("https://www.linkedin.com/jobs/view/1")
    assert seen == [vf._UA, vf._UA]


def test_get_sends_the_user_agent_it_is_given(monkeypatch):
    captured = {}

    class _Resp:
        status_code = 200
        text = "ok"

    def fake_httpx_get(url, headers=None, timeout=None, follow_redirects=None):
        captured["headers"] = headers
        return _Resp()

    import httpx
    monkeypatch.setattr(httpx, "get", fake_httpx_get)
    assert vf._get("https://x/", 1.0, ua="probe/1.0") == "ok"
    assert captured["headers"]["User-Agent"] == "probe/1.0"


def test_get_defaults_to_the_browser_user_agent(monkeypatch):
    """hh and LinkedIn need the browser UA and rely on this default. Pinning the
    VALUE matters: no other test would notice if it became _CLIENT_UA, and a
    Threads caller that forgot ua= would then look fine while returning nothing."""
    captured = {}

    class _Resp:
        status_code = 200
        text = "ok"

    def fake_httpx_get(url, headers=None, timeout=None, follow_redirects=None):
        captured["headers"] = headers
        return _Resp()

    import httpx
    monkeypatch.setattr(httpx, "get", fake_httpx_get)
    vf._get("https://x/", 1.0)
    assert captured["headers"]["User-Agent"] == vf._UA
    assert "Mozilla" in captured["headers"]["User-Agent"]
