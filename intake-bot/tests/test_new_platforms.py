"""Команды поиска по площадкам, добавленным после первой версии.

Проверка бейджей карточек («🟢 RemoteOK», «🟩 Remotive») жила здесь же и ушла
вместе с самими карточками: подтверждение найденного убрано 2026-08-22, бот
больше не рисует вакансии с кнопками ✅/❌, и рендерить нечего. Команды остались
— ими поиск и запускается с телефона.
"""
from app.domain.bot_commands import command_to_search_platform


def test_commands_map_new_platforms():
    assert command_to_search_platform("/search_remoteok") == "remoteok"
    assert command_to_search_platform("/search_remotive") == "remotive"
