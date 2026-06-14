import api.webhook as wh


def test_build_search_callbacks_exist():
    assert hasattr(wh, "_handle_callback")
    assert hasattr(wh, "_handle_command")


def test_handle_command_dispatch(monkeypatch):
    seen = {}
    monkeypatch.setattr(wh, "_do_start_search", lambda chat_id: seen.setdefault("start", chat_id))
    monkeypatch.setattr(wh, "_do_show_vacancies", lambda chat_id: seen.setdefault("show", chat_id))
    assert wh._handle_command("/start_search", 7) is True
    assert wh._handle_command("/show_vacancies", 7) is True
    assert wh._handle_command("/not_a_cmd", 7) is False
    assert seen == {"start": 7, "show": 7}


def test_handle_callback_routes(monkeypatch):
    actions = []
    monkeypatch.setattr(wh, "_do_approve", lambda cid: actions.append(("a", cid)))
    monkeypatch.setattr(wh, "_do_skip", lambda cid: actions.append(("s", cid)))
    wh._handle_callback("approve:5")
    wh._handle_callback("skip:9")
    assert actions == [("a", "5"), ("s", "9")]
