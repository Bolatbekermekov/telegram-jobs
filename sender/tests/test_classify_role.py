"""Определение роли по вакансии: чистая часть, без похода в сеть."""
from app.application.classify_role import (
    build_role_prompt,
    classify_role,
    parse_role_response,
)
from app.domain.cv_role import DEFAULT_ROLE


def test_parse_clean_json():
    assert parse_role_response('{"role": "backend-go"}') == "backend-go"


def test_parse_extracts_json_amid_prose():
    assert parse_role_response('Конечно: {"role": "qa"} готово') == "qa"


def test_parse_normalizes_shape():
    assert parse_role_response('{"role": "Backend_Node"}') == "backend-node"


def test_parse_unknown_role_falls_back():
    assert parse_role_response('{"role": "devops"}') == DEFAULT_ROLE


def test_parse_malformed_falls_back():
    assert parse_role_response("это вообще не json") == DEFAULT_ROLE
    assert parse_role_response("") == DEFAULT_ROLE


def test_prompt_lists_every_role_with_its_description():
    system, user = build_role_prompt("текст вакансии")
    assert "ai" in system and "backend-go" in system and "qa" in system
    assert "LLM" in system            # описание роли ai
    assert "текст вакансии" in user
    assert "JSON" in system


def test_classify_returns_what_the_model_said():
    class _Ok:
        def classify(self, vacancy_context):
            return "frontend"

    assert classify_role(_Ok(), "React, Next.js, вёрстка") == "frontend"


def test_classify_swallows_a_failure():
    """Обвал OpenAI не должен ронять прогон: лид получит запасное CV."""
    class _Boom:
        def classify(self, vacancy_context):
            raise RuntimeError("сеть легла")

    assert classify_role(_Boom(), "любой текст") == DEFAULT_ROLE


def test_classify_does_not_call_the_model_on_empty_text():
    """Пустая вакансия это не роль, а отсутствие данных. Платить за неё незачем."""
    class _Counting:
        calls = 0

        def classify(self, vacancy_context):
            _Counting.calls += 1
            return "ai"

    assert classify_role(_Counting(), "   ") == DEFAULT_ROLE
    assert _Counting.calls == 0
