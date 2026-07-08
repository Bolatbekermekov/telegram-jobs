"""Pure helpers for auto-answering hh.ru employer screening questions.

The browser scraping and the OpenAI call live elsewhere; here we only parse the
model's JSON answer and turn (questions, answers) into concrete fill actions, so
this logic is testable without a browser or network.

A question is a dict: {"id": str, "type": "text"|"choice", "prompt": str,
"options": list[str]}. The model returns {"answers": [{"id", "text"?, "choice"?}]}.
"""
import json


def parse_ai_answers(raw: str) -> dict:
    """Parse the model's JSON into {question_id: answer_dict}.

    Tolerates a ```json ... ``` code fence around the object.
    """
    s = raw.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
        s = s.strip()
    try:
        data = json.loads(s)
    except json.JSONDecodeError as exc:
        raise ValueError(f"model did not return valid JSON: {exc}") from exc
    out = {}
    for a in data.get("answers", []):
        qid = a.get("id")
        if qid:
            out[qid] = a
    return out


def fill_plan(questions, answers_by_id) -> list:
    """Map questions + answers to fill actions, one per question.

    ("text", id, value) for free-text, ("choice", id, index) for single-choice.
    Missing/invalid answers fall back to empty text or the first option, and
    out-of-range choices are clamped, so filling never crashes on a bad answer.
    """
    plan = []
    for q in questions:
        qid = q["id"]
        answer = answers_by_id.get(qid, {})
        if q.get("type") == "text":
            plan.append(("text", qid, str(answer.get("text", "")).strip()))
            continue
        try:
            idx = int(answer.get("choice"))
        except (TypeError, ValueError):
            idx = 0
        n = len(q.get("options", []))
        idx = max(0, min(idx, n - 1)) if n else 0
        plan.append(("choice", qid, idx))
    return plan
