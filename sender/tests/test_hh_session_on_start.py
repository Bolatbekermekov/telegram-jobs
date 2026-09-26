"""Мёртвая сессия hh ловится при старте канала, а не сжигает лиды.

Живьём 2026-09-25 (прогон 0924_2325): файл сессии на месте, кука `hhtoken`
тоже, а hh нас уже не узнаёт. Канал проверял только наличие ФАЙЛА, открывал
вакансию анонимом, hh показывал отклик по телефону без поля письма — и лиды
#1608-#1613 один за другим легли в `failed` с «поле письма не появилось»,
каждый заплатив генерацией письма. `hh_logged_in` про ровно этот случай уже
существовала, но звал её только `make login_hh`.

Теперь как у LinkedIn: мёртвая сессия — `ChannelUnavailable` при старте, лиды
остаются `new`, прогон говорит «make login_hh».
"""
import pytest

from app.domain.channel import ChannelUnavailable
from app.infrastructure.channels import headhunter as hh
from app.infrastructure.channels.headhunter import SEL_LOGIN, SEL_USER_MENU


class _Locator:
    def __init__(self, n):
        self._n = n

    def count(self):
        return self._n


class _Page:
    def __init__(self, logged_in):
        self._logged_in = logged_in
        self.visited = []

    def goto(self, url, **kw):
        self.visited.append(url)

    def wait_for_timeout(self, ms):
        pass

    def locator(self, sel):
        if sel == SEL_LOGIN:
            return _Locator(0 if self._logged_in else 1)
        if sel == SEL_USER_MENU:
            return _Locator(1 if self._logged_in else 0)
        return _Locator(0)


def _fake_playwright(monkeypatch, page):
    closed = []

    class _Browser:
        def new_context(self, **kw):
            return type("Ctx", (), {"new_page": lambda s: page})()

        def close(self):
            closed.append("browser")

    class _PW:
        chromium = type("Ch", (), {"launch": lambda s, **kw: _Browser()})()

        def stop(self):
            closed.append("pw")

    monkeypatch.setattr("patchright.sync_api.sync_playwright",
                        lambda: type("S", (), {"start": lambda s: _PW()})())
    return closed


def test_a_dead_session_stops_the_channel_at_start(monkeypatch, tmp_path):
    state = tmp_path / "hh_state.json"
    state.write_text("{}")
    closed = _fake_playwright(monkeypatch, _Page(logged_in=False))
    ch = hh.HeadHunterChannel(str(state))
    with pytest.raises(ChannelUnavailable, match="make login_hh"):
        ch.start()
    assert "browser" in closed, "браузер мёртвой сессии не должен висеть"


def test_a_live_session_starts_as_before(monkeypatch, tmp_path):
    state = tmp_path / "hh_state.json"
    state.write_text("{}")
    page = _Page(logged_in=True)
    _fake_playwright(monkeypatch, page)
    ch = hh.HeadHunterChannel(str(state))
    ch.start()
    assert page.visited and "hh.ru" in page.visited[0]
