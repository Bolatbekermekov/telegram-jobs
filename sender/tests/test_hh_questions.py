import pytest

from app.application.hh_questions import fill_plan, parse_ai_answers


def test_parse_plain_json():
    raw = '{"answers": [{"id": "task_1", "text": "hello"}, {"id": "task_2", "choice": 2}]}'
    got = parse_ai_answers(raw)
    assert got["task_1"]["text"] == "hello"
    assert got["task_2"]["choice"] == 2


def test_parse_json_in_code_fence():
    raw = '```json\n{"answers": [{"id": "task_1", "text": "hi"}]}\n```'
    assert parse_ai_answers(raw)["task_1"]["text"] == "hi"


def test_parse_invalid_json_raises():
    with pytest.raises(ValueError):
        parse_ai_answers("not json at all")


def test_fill_plan_text_and_choice():
    questions = [
        {"id": "task_1", "type": "text", "prompt": "About you", "options": []},
        {"id": "task_2", "type": "choice", "prompt": "Pick", "options": ["a", "b", "c"]},
    ]
    answers = {"task_1": {"id": "task_1", "text": " done "}, "task_2": {"id": "task_2", "choice": 1}}
    assert fill_plan(questions, answers) == [
        ("text", "task_1", "done"),
        ("choice", "task_2", 1),
    ]


def test_fill_plan_clamps_out_of_range_choice():
    questions = [{"id": "q", "type": "choice", "prompt": "p", "options": ["a", "b"]}]
    assert fill_plan(questions, {"q": {"id": "q", "choice": 9}}) == [("choice", "q", 1)]


def test_fill_plan_defaults_missing_answer():
    questions = [
        {"id": "t", "type": "text", "prompt": "p", "options": []},
        {"id": "c", "type": "choice", "prompt": "p", "options": ["a", "b"]},
    ]
    plan = fill_plan(questions, {})
    assert plan == [("text", "t", ""), ("choice", "c", 0)]


def test_fill_plan_non_integer_choice_defaults_to_zero():
    questions = [{"id": "c", "type": "choice", "prompt": "p", "options": ["a", "b"]}]
    assert fill_plan(questions, {"c": {"id": "c", "choice": "nope"}}) == [("choice", "c", 0)]
