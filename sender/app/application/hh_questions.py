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
        if not isinstance(a, dict):
            continue
        qid = a.get("id")
        # Key by STRING, always. The prompt asks for "id":"<id>" but models answer
        # with a bare number as often as not, and question ids are strings — so a
        # numeric id silently matched nothing and the answer was dropped on the
        # floor. Every free-text question in every external form came back
        # unanswered because of this (measured 2026-07-29: the model answered the
        # essay, `{1: {...}}`, and the lookup for "1" missed).
        #
        # `is not None`, not truthiness: question ids start at "0", and an integer
        # 0 is falsy — the FIRST question's answer was thrown away twice over.
        if qid is not None:
            out[str(qid)] = a
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
        # str() on both sides — see parse_ai_answers for why the model's ids can't
        # be trusted to keep their type.
        answer = answers_by_id.get(str(qid)) or answers_by_id.get(qid) or {}
        if not isinstance(answer, dict):
            answer = {}
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
