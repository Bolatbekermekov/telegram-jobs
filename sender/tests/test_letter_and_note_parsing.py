"""Разбор ответа модели, которая просят вернуть письмо и записку сразу.

Записка не может быть куском письма: у неё жёсткий предел площадки и своя задача
(зачем принимать контакт). Просим оба текста одним запросом, но ответ модели это
чужой текст, и разбор обязан выдерживать всё, что она может прислать. Потерять
записку не страшно — вызывающий сократит письмо. Потерять письмо нельзя.
"""
import pytest

from app.infrastructure.openai_client import _parse_letter_and_note


def test_parses_both_fields():
    raw = '{"letter": "Полное письмо.", "note": "Короткая записка."}'
    assert _parse_letter_and_note(raw) == ("Полное письмо.", "Короткая записка.")


def test_parses_a_fenced_json_block():
    """Модели любят заворачивать JSON в ```json."""
    raw = '```json\n{"letter": "Письмо.", "note": "Записка."}\n```'
    assert _parse_letter_and_note(raw) == ("Письмо.", "Записка.")


def test_plain_prose_becomes_the_letter_with_no_note():
    """Модель проигнорировала формат, но письмо написала годное — лид из-за
    обёртки терять нельзя."""
    assert _parse_letter_and_note("Здравствуйте. Пишу по вакансии.") == (
        "Здравствуйте. Пишу по вакансии.", "")


def test_an_empty_note_field_is_no_note():
    assert _parse_letter_and_note('{"letter": "Письмо.", "note": ""}') == ("Письмо.", "")


def test_a_json_array_is_not_a_result():
    """Массив это тоже валидный JSON, но не объект с letter/note — ответ, который
    пытался быть JSON и не дал письма, поднимается как сбой генерации."""
    with pytest.raises(ValueError):
        _parse_letter_and_note('["a", "b"]')


def test_a_json_object_without_a_letter_is_a_generation_failure():
    """Объект распарсился, но без letter отправлять нечего — это не письмо
    без обёртки, а поломанная генерация, и её нельзя тихо спутать с прозой."""
    with pytest.raises(ValueError):
        _parse_letter_and_note('{"note": "только записка"}')


def test_fenced_prose_loses_the_fence_not_just_the_json():
    """Модель завернула ответ в ``` и не выдала JSON. Письмо всё равно годное, но
    маркеры ограждения в него попасть не должны: их прочитает живой человек."""
    raw = "```\nЗдравствуйте. Пишу по вакансии.\n```"
    assert _parse_letter_and_note(raw) == ("Здравствуйте. Пишу по вакансии.", "")


def test_a_broken_json_object_is_a_generation_failure_not_a_letter():
    """Живая поломка: `_SYSTEM` требует абзацы, а перевод строки внутри строки
    JSON ломает разбор. Отдать такой обрубок за письмо значит показать
    рекрутёру `{"letter": "Здравствуйте.` — лучше не отправить вовсе."""
    with pytest.raises(ValueError):
        _parse_letter_and_note('{"letter": "Здравствуйте.\nСейчас работаю в')


def test_a_truncated_json_object_is_a_generation_failure():
    with pytest.raises(ValueError):
        _parse_letter_and_note('{"letter": "Здравствуйте, пишу по вакансии", "not')
