"""Подписи внутри письма пишутся на языке письма, а не на языке промпта.

Формат письма задан промптом дословно, в кавычках и по-русски: «строкой
'Мой стек:'» и «отдельным предложением 'Плюс к пониманию системы целиком:'»
(openai_client._SYSTEM). Рядом language_rule('en') требует «без единого
русского слова». Промпт противоречив, и модели разрешают конфликт по-разному:
замер 2026-09-07 — gemini-3.5-flash перевёл подписи во всех трёх письмах,
gemini-3.5-flash-lite во всех трёх оставил русские, получив английское письмо
со строкой «Мой стек: MongoDB, Express…». Такое уходит живому HR.

Чинить надо промпт, а не выбирать модель посильнее: послушная модель не
виновата, что ей велели две несовместимые вещи.
"""
from app.domain.message_language import language_rule
from app.infrastructure.openai_client import _SYSTEM

RU_LABELS = ("Мой стек", "Плюс к пониманию системы целиком")


def test_the_format_rule_still_dictates_the_labels_verbatim():
    # Это не претензия к промпту, а фиксация исходных данных: подписи заданы
    # дословно, поэтому правило языка обязано сказать про них отдельно.
    assert all(label in _SYSTEM for label in RU_LABELS)


def test_english_rule_gives_the_english_labels():
    rule = language_rule("en")
    assert "My stack:" in rule, "не сказано, как подпись выглядит по-английски"
    assert "Плюс к пониманию" not in rule or "Plus" in rule


def test_english_rule_names_what_exactly_must_not_survive():
    # Общего «пиши по-английски» не хватило: flash-lite считал подпись частью
    # ФОРМАТА, а не текста. Поэтому называем её прямо.
    rule = language_rule("en")
    assert any(label in rule for label in RU_LABELS), \
        "правило не называет русские подписи, которые нельзя оставлять"


def test_russian_rule_keeps_the_original_labels():
    # В русском письме подписи и так русские — ничего дополнительного не нужно,
    # и лишний абзац только разбавил бы промпт.
    rule = language_rule("ru")
    assert "My stack:" not in rule


def test_the_assembled_prompt_for_an_english_vacancy_is_not_contradictory():
    prompt = _SYSTEM + language_rule("en")
    assert "My stack:" in prompt
    assert "Мой стек" in prompt  # формат остался
