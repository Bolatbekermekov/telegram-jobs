"""Оценка «подходит ли вакансия профилю»: промпт и разбор ответа модели.

Это интейковая копия ноутбучной логики (sender/app/application/relevance.py) —
две половины деплоятся отдельно и друг друга не импортируют, как contact.py и
lead.py. Тесты здесь стерегут ровно то, ради чего копия сделана: тот же промпт
(иначе оценки поиска и интейка несравнимы) и ОДНО намеренное расхождение в
разборе ответа.
"""
import inspect
from pathlib import Path

import pytest

from app.application import relevance
from app.application.relevance import build_score_prompt, parse_score_response
from app.search_profile import SEARCH_PROFILE

# Профиль поиска у интейка свой (в Vercel .txt из sender/ не доезжает — см.
# app/search_profile.py), но копия обязана быть дословной.
_LAPTOP_PROFILE = Path(__file__).resolve().parents[2] / "sender" / "search_profile.txt"
_LAPTOP_RELEVANCE = (Path(__file__).resolve().parents[2]
                     / "sender" / "app" / "application" / "relevance.py")


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



def _laptop_source() -> str:
    if not _LAPTOP_RELEVANCE.exists():
        pytest.skip("ноутбучной половины рядом нет — деплой интейка отдельный")
    return _LAPTOP_RELEVANCE.read_text(encoding="utf-8")


def _constant_block(text: str, name: str) -> str:
    """Исходник константы вида `name = (` … `\\n)` целиком, вместе со скобками."""
    start = text.index(f"{name} = (")
    return text[start:text.index("\n)", start) + 2]


def test_the_prompt_is_still_the_laptops_prompt_word_for_word():
    """Ловит расхождение промптов так же механически, как расхождение профилей.

    Формулировка промпта — это не стиль, а вердикт: правка 2026-08-28 (шкала
    вместо «будь строгим», уровни только из профиля, стаж и неудалённый формат
    балл не снижают) подняла #422 QA Engineer с 18..38 (0 проходов из 38) до
    68..80 (22 из 22) при пороге 60. Уедет одна копия — оценка пересланной
    вакансии и оценка найденной поиском лягут в одну колонку одной таблицы,
    означая разное.
    """
    theirs = _laptop_source()
    ours = Path(inspect.getfile(relevance)).read_text(encoding="utf-8")
    assert _constant_block(ours, "_SCORE_SYSTEM") in theirs, (
        "_SCORE_SYSTEM разошёлся с sender/app/application/relevance.py — "
        "правится одна копия, переносится в обе."
    )
    assert inspect.getsource(build_score_prompt) in theirs, (
        "build_score_prompt разошлась с sender/app/application/relevance.py — "
        "правится одна копия, переносится в обе."
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


def test_the_location_reaches_the_model_and_an_empty_one_leaves_no_label():
    """Пересланной вакансии локация не достаётся (у интейка есть только текст
    сообщения), но параметр здесь такой же, как у ноутбучной копии: разъедься
    сигнатуры — и промпты перестали бы совпадать дословно, ради чего копия и
    сделана. Пустая локация подписи после себя не оставляет.
    """
    _, user = build_score_prompt("PROF", "TITLE", "DESC", "🇰🇿 Kazakhstan")
    assert "🇰🇿 Kazakhstan" in user

    _, without = build_score_prompt("PROF", "TITLE", "DESC")
    assert "Локация" not in without


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
