import api.webhook as wh


def test_build_search_callbacks_exist():
    assert hasattr(wh, "_handle_callback")
    assert hasattr(wh, "_handle_command")


def test_handle_command_dispatch(monkeypatch):
    seen = []
    monkeypatch.setattr(wh, "_do_start_search",
                        lambda chat_id, platform: seen.append(("start", chat_id, platform)))
    monkeypatch.setattr(wh, "_do_show_vacancies", lambda chat_id: seen.append(("show", chat_id)))
    assert wh._handle_command("/start_search", 7) is True
    assert wh._handle_command("/search_linkedin", 7) is True
    assert wh._handle_command("/search_wellfound", 7) is True
    assert wh._handle_command("/show_vacancies", 7) is True
    assert wh._handle_command("/not_a_cmd", 7) is False
    assert seen == [
        ("start", 7, "all"),
        ("start", 7, "linkedin"),
        ("start", 7, "wellfound"),
        ("show", 7),
    ]


def test_handle_callback_routes(monkeypatch):
    actions = []
    monkeypatch.setattr(wh, "_do_approve", lambda cid: actions.append(("a", cid)))
    monkeypatch.setattr(wh, "_do_skip", lambda cid: actions.append(("s", cid)))
    wh._handle_callback("approve:5")
    wh._handle_callback("skip:9")
    assert actions == [("a", "5"), ("s", "9")]


class _FakeRequest:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


def test_start_search_command_reaches_handler_not_welcome(monkeypatch):
    """Regression: /start_search must NOT be swallowed by the /start branch."""
    import asyncio

    monkeypatch.setattr(wh.config, "TELEGRAM_WEBHOOK_SECRET", "", raising=False)
    calls, replies = [], []
    monkeypatch.setattr(wh, "_do_start_search", lambda chat_id, platform: calls.append(chat_id))
    monkeypatch.setattr(wh, "_reply", lambda chat_id, text: replies.append(text))

    update = {"message": {"chat": {"id": 5}, "text": "/start_search"}}
    res = asyncio.run(wh.telegram_webhook(_FakeRequest(update), ""))

    assert res == {"ok": True}
    assert calls == [5]      # reached the search handler
    assert replies == []     # NOT the welcome message


def test_plain_start_still_shows_welcome(monkeypatch):
    """/start (exact) still routes to the welcome reply."""
    import asyncio

    monkeypatch.setattr(wh.config, "TELEGRAM_WEBHOOK_SECRET", "", raising=False)
    calls, replies = [], []
    monkeypatch.setattr(wh, "_do_start_search", lambda chat_id, platform: calls.append(chat_id))
    monkeypatch.setattr(wh, "_reply", lambda chat_id, text: replies.append(text))

    update = {"message": {"chat": {"id": 5}, "text": "/start"}}
    asyncio.run(wh.telegram_webhook(_FakeRequest(update), ""))

    assert calls == []                       # search handler not triggered
    assert replies and "Привет" in replies[0]
