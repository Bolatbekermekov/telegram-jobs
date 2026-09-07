"""`make login_hh` обязан смотреть на живость сессии, а не на наличие файла.

До 2026-09-07 команда отказывалась работать, если файл существует: «Сессия
hh.ru уже есть. Удали этот файл, если хочешь перелогиниться». Мёртвую сессию так
не обновить вовсе — а мёртвой она становится молча, куки в файле при этом не
просрочены (у hhtoken оставалось 384 дня). Обходили руками: рядом лежат
hh_state.json.dead-2026-08-22 и .dead-2026-09-07 — то есть капкан сработал
дважды.

Симптом на другом конце: прогон валит все hh-лиды в `failed` с «поле письма не
появилось». Поля и правда нет — анониму hh показывает отклик по телефону.
"""
import json
from datetime import date
from pathlib import Path

from app.infrastructure.channels.headhunter import hh_logged_in
from app.infrastructure.session_state import retire_dead_state


class _Page:
    """Страница, о которой известно только, сколько чего на ней найдено."""

    def __init__(self, counts):
        self._counts = counts

    def locator(self, selector):
        count = self._counts.get(selector, 0)
        return type("L", (), {"count": lambda self, c=count: c})()


def test_login_link_means_we_are_anonymous():
    from app.infrastructure.channels.headhunter import SEL_LOGIN
    assert hh_logged_in(_Page({SEL_LOGIN: 1})) is False


def test_user_menu_without_login_link_means_we_are_in():
    from app.infrastructure.channels.headhunter import SEL_USER_MENU
    assert hh_logged_in(_Page({SEL_USER_MENU: 1})) is True


def test_neither_marker_is_treated_as_dead():
    # Осторожность в нужную сторону: лишний перелогин стоит минуту, а работа с
    # мёртвой сессией — всех hh-лидов прогона.
    assert hh_logged_in(_Page({})) is False


def test_dead_state_is_moved_aside_not_deleted(tmp_path):
    state = tmp_path / "hh_state.json"
    state.write_text(json.dumps({"cookies": [{"name": "hhtoken"}]}), encoding="utf-8")

    moved = retire_dead_state(state, date(2026, 9, 7))

    assert not state.exists(), "старый файл должен уехать с дороги"
    assert moved.exists(), "и при этом сохраниться"
    assert "2026-09-07" in moved.name
    assert json.loads(moved.read_text())["cookies"][0]["name"] == "hhtoken"


def test_second_retirement_the_same_day_does_not_overwrite_the_first(tmp_path):
    state = tmp_path / "hh_state.json"
    state.write_text("первый", encoding="utf-8")
    first = retire_dead_state(state, date(2026, 9, 7))
    state.write_text("второй", encoding="utf-8")
    second = retire_dead_state(state, date(2026, 9, 7))

    assert first != second
    assert first.read_text() == "первый"
    assert second.read_text() == "второй"


def test_missing_file_is_not_an_error(tmp_path):
    assert retire_dead_state(tmp_path / "нет.json", date(2026, 9, 7)) is None


# --- проводка в саму команду ---

def _state(tmp_path, monkeypatch):
    from app import config
    p = tmp_path / "hh_state.json"
    p.write_text('{"cookies": []}', encoding="utf-8")
    monkeypatch.setattr(config, "HH_STATE_PATH", str(p))
    return p


def test_live_session_is_left_alone(tmp_path, monkeypatch, capsys):
    from app.interface.cli import run_login_hh
    state = _state(tmp_path, monkeypatch)

    run_login_hh(session_alive=lambda _: True)

    assert state.exists(), "живую сессию трогать нельзя"
    out = capsys.readouterr().out
    assert "жива" in out


def test_dead_session_is_retired_instead_of_refusing(tmp_path, monkeypatch, capsys):
    # Главное отличие от старого поведения: команда не упирается в «файл уже
    # есть», а убирает мёртвый файл и идёт логиниться.
    from app.interface.cli import run_login_hh
    state = _state(tmp_path, monkeypatch)
    launched = []
    monkeypatch.setattr("subprocess.Popen", lambda *a, **k: launched.append(a))
    monkeypatch.setattr("builtins.input", lambda *_: "")
    # И браузер тоже: без этого patchright уходит поднимать Chrome по-настоящему
    # (да ещё и через подменённый Popen) и сыплет асинхронным мусором в вывод.
    def _no_browser():
        raise RuntimeError("браузер в тесте не поднимаем")
    monkeypatch.setattr("patchright.sync_api.sync_playwright", _no_browser)

    run_login_hh(session_alive=lambda _: False)

    assert not state.exists(), "мёртвый файл должен уехать с дороги"
    assert list(tmp_path.glob("hh_state.dead-*.json")), "но сохраниться рядом"
    out = capsys.readouterr().out
    assert "Удали этот файл" not in out, "старый тупиковый совет должен уйти"
