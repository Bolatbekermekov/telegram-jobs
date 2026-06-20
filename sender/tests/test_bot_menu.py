import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location(
    "register_bot_menu", Path(__file__).resolve().parents[1] / "register_bot_menu.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


def test_payload_lists_per_platform_search_commands():
    names = [c["command"] for c in _mod.bot_commands_payload()]
    assert "start_search" in names
    assert "search_linkedin" in names
    assert "search_wellfound" in names


def test_every_command_has_a_description():
    assert all(c.get("description") for c in _mod.bot_commands_payload())
