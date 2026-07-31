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


# --- the model's ids can't be trusted to keep their type ---------------------

def test_a_numeric_id_from_the_model_still_matches_its_question():
    """Measured 2026-07-29: the model answered with `"id": 1`, the lookup asked for
    "1", and the answer was dropped — silently, for every free-text question in
    every external application form."""
    answers = parse_ai_answers(
        '{"answers":[{"id":1,"text":"Мой ответ"}]}')
    plan = fill_plan([{"id": "1", "type": "text", "prompt": "Q"}], answers)

    assert plan == [("text", "1", "Мой ответ")]


def test_the_first_question_is_not_thrown_away_by_a_falsy_id():
    """Ids start at "0", and an integer 0 is falsy — `if qid:` dropped it."""
    answers = parse_ai_answers('{"answers":[{"id":0,"text":"Первый"}]}')
    assert fill_plan([{"id": "0", "type": "text", "prompt": "Q"}], answers) == [
        ("text", "0", "Первый")]


def test_a_string_id_keeps_working():
    answers = parse_ai_answers('{"answers":[{"id":"7","text":"ок"}]}')
    assert fill_plan([{"id": "7", "type": "text", "prompt": "Q"}], answers) == [
        ("text", "7", "ок")]


def test_a_numeric_id_matches_a_choice_question_too():
    answers = parse_ai_answers('{"answers":[{"id":2,"choice":1}]}')
    plan = fill_plan([{"id": "2", "type": "choice", "prompt": "Q",
                       "options": ["a", "b", "c"]}], answers)
    assert plan == [("choice", "2", 1)]


def test_a_non_dict_answer_does_not_crash_the_fill():
    answers = parse_ai_answers('{"answers":["мусор",{"id":1,"text":"ок"}]}')
    assert fill_plan([{"id": "1", "type": "text", "prompt": "Q"}], answers) == [
        ("text", "1", "ок")]
