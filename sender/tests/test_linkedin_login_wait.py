"""Вход в LinkedIn ждёт живую `li_at` в куках окна, а не нажатия Enter.

`LinkedInSearcher.start()` при мёртвой сессии открывал окно входа и звал
`input()`. Из терминала без TTY — прогон агента, запуск в фоне, воркер — вызов
падал на EOFError мгновенно, `login_all` глотал исключение и закрывал окно, и
новая сессия не сохранялась никогда. Всплыло 2026-09-13 при переходе на новый
аккаунт: окно закрылось бы раньше, чем человек успел бы в него посмотреть. Тот
же капкан уже захлопывался на входах Wellfound и Indeed и чинился там тем же —
опросом.

Сигнал входа ровно тот, что у `has_valid_session`: непустая и не истёкшая
`li_at`. Гостевые куки (JSESSIONID, bcookie, lidc) есть и без входа.
"""
import builtins

import pytest

from app.infrastructure.linkedin_session import wait_for_login
from app.infrastructure.search.linkedin_search import LinkedInSearcher

_FUTURE = 4_102_444_800.0   # 2100-01-01
_PAST = 1_000_000_000.0     # 2001-09-09
_GUEST = [{"name": "JSESSIONID", "value": "ajax:1", "expires": _FUTURE},
          {"name": "bcookie", "value": "v=2", "expires": _FUTURE}]
_LIVE = _GUEST + [{"name": "li_at", "value": "AQED...", "expires": _FUTURE}]


class _Context:
    """Куки окна по очереди: каждый опрос — следующий снимок, последний держится."""

    def __init__(self, snapshots):
        self._snapshots = list(snapshots)
        self.asked = []
        self.saved = None
        self.pages = []

    def cookies(self, *urls):
        self.asked.append(urls)
        return self._snapshots.pop(0) if len(self._snapshots) > 1 else self._snapshots[0]

    def new_page(self):
        page = _Page()
        self.pages.append(page)
        return page

    def storage_state(self, path=None):
        self.saved = path


class _Page:
    def __init__(self):
        self.visited = []

    def goto(self, url, **kw):
        self.visited.append(url)


# --- ожидание ---------------------------------------------------------------------

def test_the_login_is_seen_as_soon_as_li_at_appears():
    slept = []
    assert wait_for_login(_Context([[], _GUEST, _LIVE]), wait_seconds=30, poll_seconds=3,
                          sleep=slept.append)
    assert slept == [3, 3]


def test_the_cookies_are_asked_for_linkedin_itself():
    ctx = _Context([_LIVE])
    wait_for_login(ctx, wait_seconds=30, poll_seconds=3, sleep=lambda s: None)
    assert any("linkedin.com" in url for urls in ctx.asked for url in urls)


def test_guest_cookies_are_not_a_login():
    assert not wait_for_login(_Context([_GUEST]), wait_seconds=9, poll_seconds=3,
                              sleep=lambda s: None)


def test_an_empty_or_expired_li_at_is_not_a_login():
    empty = _GUEST + [{"name": "li_at", "value": "", "expires": _FUTURE}]
    expired = _GUEST + [{"name": "li_at", "value": "AQED...", "expires": _PAST}]
    for snapshot in (empty, expired):
        assert not wait_for_login(_Context([snapshot]), wait_seconds=9, poll_seconds=3,
                                  sleep=lambda s: None)


def test_waiting_ends_after_the_given_time():
    slept = []
    assert not wait_for_login(_Context([[]]), wait_seconds=12, poll_seconds=3,
                              sleep=slept.append)
    assert 0 < sum(slept) <= 12


# --- окно входа -------------------------------------------------------------------

class _Browser:
    def __init__(self, context):
        self._context = context

    def new_context(self, storage_state=None, **kw):
        return self._context


class _Playwright:
    def __init__(self, browser):
        self._browser = browser
        self.chromium = self

    def start(self):
        return self

    def launch(self, headless=True, **kw):
        return self._browser

    def stop(self):
        pass


def _no_input(*args):
    raise AssertionError("input() без TTY падает на EOFError — ждать надо опросом")


def _searcher_without_session(monkeypatch, tmp_path, snapshots):
    import playwright.sync_api as sync_api
    ctx = _Context(snapshots)
    monkeypatch.setattr(sync_api, "sync_playwright", lambda: _Playwright(_Browser(ctx)))
    monkeypatch.setattr(builtins, "input", _no_input)
    state = tmp_path / "linkedin_state.json"
    s = LinkedInSearcher(str(state), headless=False,
                         login_wait_seconds=6, login_sleep=lambda seconds: None)
    return s, ctx, state


def test_a_login_window_saves_the_session_once_li_at_appears(monkeypatch, tmp_path):
    s, ctx, state = _searcher_without_session(monkeypatch, tmp_path, [[], _LIVE])
    s.start()
    assert ctx.pages[0].visited == ["https://www.linkedin.com/login"]
    assert ctx.saved == str(state)


def test_a_login_that_never_happens_saves_nothing_and_says_so(monkeypatch, tmp_path):
    """Сохранить гостевые куки хуже, чем не сохранить ничего: файл выглядел бы
    сессией, и каждый профиль упирался бы в authwall (см. test_linkedin_session)."""
    s, ctx, _ = _searcher_without_session(monkeypatch, tmp_path, [_GUEST])
    with pytest.raises(RuntimeError, match="не дождался входа"):
        s.start()
    assert ctx.saved is None
