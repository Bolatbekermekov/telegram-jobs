from app.application.relevance import build_score_prompt, parse_score_response


def test_parse_clean_json():
    assert parse_score_response('{"score": 82, "reason": "Go backend + AI agents"}') == (
        82, "Go backend + AI agents")


def test_parse_extracts_json_amid_prose_and_clamps():
    assert parse_score_response('Sure: {"score": 200, "reason": "x"} done') == (100, "x")


def test_parse_malformed_returns_zero():
    assert parse_score_response("not json at all") == (0, "")


def test_build_score_prompt_includes_inputs():
    system, user = build_score_prompt("PROF", "TITLE", "DESC")
    assert "JSON" in system or "json" in system
    assert "PROF" in user and "TITLE" in user and "DESC" in user
