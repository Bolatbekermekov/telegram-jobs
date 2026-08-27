from register_bot_menu import bot_commands_payload


def test_menu_has_new_search_commands():
    commands = {c["command"] for c in bot_commands_payload()}
    assert "search_remoteok" in commands
    assert "search_remotive" in commands


def test_menu_has_remocate_search_command():
    commands = {c["command"] for c in bot_commands_payload()}
    assert "search_remocate" in commands


def test_menu_has_hh_search_command():
    commands = {c["command"] for c in bot_commands_payload()}
    assert "search_hh" in commands
