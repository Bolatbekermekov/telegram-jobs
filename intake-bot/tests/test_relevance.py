"""Оценка «подходит ли вакансия профилю»: промпт и разбор ответа модели.

Это интейковая копия ноутбучной логики (sender/app/application/relevance.py) —
две половины деплоятся отдельно и друг друга не импортируют, как contact.py и
lead.py. Тесты здесь стерегут ровно то, ради чего копия сделана: тот же промпт
(иначе оценки поиска и интейка несравнимы) и ОДНО намеренное расхождение в
разборе ответа.
"""
from pathlib import Path

import pytest

from app.application.relevance import build_score_prompt, parse_score_response
from app.search_profile import SEARCH_PROFILE

# Профиль поиска у интейка свой (в Vercel .txt из sender/ не доезжает — см.
# app/search_profile.py), но копия обязана быть дословной.
_LAPTOP_PROFILE = Path(__file__).resolve().parents[2] / "sender" / "search_profile.txt"


@pytest.mark.skipif(not _LAPTOP_PROFILE.exists(),
                    reason="ноутбучной половины рядом нет — деплой интейка отдельный")
def test_the_bundled_profile_still_matches_the_laptops_one():
    """Ловит молчаливое расхождение двух копий профиля.

    Владелец правит sender/search_profile.txt, когда меняет то, что ищет. Забыть
    вторую копию ничего не сломает видимо: бот продолжит отвечать оценками — но
    пересланная вакансия будет меряться старым профилем, найденная поиском новым,
    а цифры лягут в одну колонку одной таблицы и станут несравнимы.

    Чинится копированием: заменить строку SEARCH_PROFILE в app/search_profile.py
    текстом файла целиком.
    """
    assert SEARCH_PROFILE.strip() == _LAPTOP_PROFILE.read_text(encoding="utf-8").strip(), (
        "intake-bot/app/search_profile.py разошёлся с sender/search_profile.txt — "
        "перенеси текст файла в константу SEARCH_PROFILE целиком."
    )



def test_prompt_carries_the_profile_and_the_vacancy():
    """Без профиля в промпте модель оценивает «хорошая ли это вакансия вообще»,
    а вопрос стоит «подходит ли она ЭТОМУ человеку»."""
    system, user = build_score_prompt(
        "Уровень: Junior / Middle. НЕ senior/lead/staff.",
        "Principal Software Engineer",
        "We are looking for a Principal engineer to lead the platform team.")

    assert "JSON" in system
    assert "НЕ senior/lead/staff" in user
    assert "Principal Software Engineer" in user
    assert "lead the platform team" in user


def test_reads_the_score_and_the_reason():
    assert parse_score_response(
        '{"score": 35, "reason": "Principal, профиль до Middle"}'
    ) == (35, "Principal, профиль до Middle")


def test_a_json_wrapped_in_prose_is_still_read():
    """Дешёвая модель любит обрамить JSON словами. Требовать чистый JSON значит
    терять оценку там, где модель на самом деле ответила."""
    assert parse_score_response(
        'Вот оценка: {"score": 82, "reason": "Junior Full-Stack"} — готово'
    ) == (82, "Junior Full-Stack")


def test_a_malformed_answer_is_not_a_verdict():
    """Главное расхождение с ноутбучной копией: там мусор превращается в 0, и
    это безопасно — 0 значит «отбросить», ценой в одну вакансию.

    Здесь оценка ЛОЖИТСЯ В «Заметку» и уходит владельцу в ответ, поэтому 0/100
    прочиталось бы как приговор, которого модель не выносила: «не подходит» и
    «не смогли спросить» — разные вещи, и вторую надо уметь показать пустотой.
    """
    assert parse_score_response("извини, не могу") is None
    assert parse_score_response("") is None
    assert parse_score_response('{"reason": "score забыл"}') is None


def test_a_score_out_of_range_is_clamped_not_dropped():
    """Модель иногда отвечает 140 или -5. Это всё ещё вердикт, просто в чужой
    шкале, и терять его целиком дороже, чем прижать к границе."""
    assert parse_score_response('{"score": 140, "reason": "идеально"}') == (100, "идеально")
    assert parse_score_response('{"score": -5, "reason": "мимо"}') == (0, "мимо")
