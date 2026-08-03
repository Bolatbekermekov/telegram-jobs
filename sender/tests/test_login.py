from app.application.login import (
    LOGIN_ORDER,
    login_all,
    platforms_needing_login,
    telegram_session_file,
)


class _FakeSearcher:
    def __init__(self, name):
        self.name = name
        self.events = []

    def start(self):
        self.events.append("start")

    def stop(self):
        self.events.append("stop")


def test_login_all_starts_then_stops_each_in_order():
    a, b = _FakeSearcher("linkedin"), _FakeSearcher("wellfound")
    done = login_all([a, b])
    assert done == ["linkedin", "wellfound"]
    assert a.events == ["start", "stop"]
    assert b.events == ["start", "stop"]


def test_login_all_stops_even_if_start_fails_and_continues():
    boom = _FakeSearcher("linkedin")

    def explode():
        boom.events.append("start")
        raise RuntimeError("login window crashed")

    boom.start = explode
    ok = _FakeSearcher("wellfound")

    done = login_all([boom, ok])
    # the broken one is reported as not-done, but its session is still closed...
    assert "stop" in boom.events
    # ...and the next searcher still runs
    assert done == ["wellfound"]
    assert ok.events == ["start", "stop"]


def test_telegram_session_file_appends_telethon_suffix():
    assert telegram_session_file("sender/userbot") == "sender/userbot.session"


def test_platforms_needing_login_keeps_order_and_skips_existing():
    has = {"telegram": True, "linkedin": False, "hh": False, "remoteok": True,
           "threads": False, "wellfound": True}
    assert platforms_needing_login(has) == ["linkedin", "hh", "threads"]


def test_threads_is_in_the_login_order():
    assert "threads" in LOGIN_ORDER


def test_threads_logs_in_before_wellfound():
    """Wellfound's Chrome stays open for CDP and must stay last."""
    assert LOGIN_ORDER.index("threads") < LOGIN_ORDER.index("wellfound")


def test_platforms_needing_login_unknown_platform_means_login():
    assert platforms_needing_login({}) == LOGIN_ORDER


def test_wellfound_logs_in_last():
    # Its Chrome stays open for CDP, so it must not block the other logins.
    assert LOGIN_ORDER[-1] == "wellfound"


def test_remoteok_is_in_the_login_order():
    """Без сессии RemoteOK отклик невозможен: кнопка Apply уводит гостя на
    /sign-up. Площадка, которой нет в `make login`, тихо остаётся незалогиненной
    — а узнаётся это только на первом отклике."""
    assert "remoteok" in LOGIN_ORDER


def test_remoteok_logs_in_before_wellfound():
    """Его Chrome закрывается сразу после выгрузки куки, а wellfound-овский
    обязан остаться открытым — значит remoteok идёт раньше."""
    assert LOGIN_ORDER.index("remoteok") < LOGIN_ORDER.index("wellfound")
