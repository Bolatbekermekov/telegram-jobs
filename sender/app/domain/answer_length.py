"""Потолок длины свободного ответа в анкете. Чистая логика.

Решение владельца 2026-09-25: отвечать подробно, но не длиннее 500 знаков.
Модели это сказано в промпте (`_QUESTIONS_SYSTEM`), а здесь страховка на
случай, если она не уложится: ответ режется по концу последнего ЦЕЛОГО
предложения. Оборванная на полуслове фраза уехала бы работодателю, и читает
её человек.
"""
import re

MAX_ANSWER_CHARS = 500

# Конец предложения: точка, «!» или «?», за которыми пробел или конец строки.
# Точка внутри «Atlanti.ai» или «3.5» концом не считается.
_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")
_CLAUSE_END = re.compile(r"[,;:](?=\s)")


def cap_answer(text: str, limit: int = MAX_ANSWER_CHARS) -> str:
    """Ответ не длиннее `limit`: целиком, если влезает, иначе до конца предложения."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    head = text[:limit]
    ends = [m.end() for m in _SENTENCE_END.finditer(head)]
    if ends:
        return head[:ends[-1]].strip()
    # Одно бесконечное предложение: режем по последней запятой, иначе по слову,
    # и закрываем точкой, чтобы ответ не висел на полуслове.
    room = head[:limit - 1]
    clauses = [m.start() for m in _CLAUSE_END.finditer(room)]
    cut = clauses[-1] if clauses else room.rstrip().rfind(" ")
    return (room[:cut] if cut > 0 else room).rstrip(" ,;:") + "."


def cap_answers(answers: dict, limit: int = MAX_ANSWER_CHARS) -> dict:
    """То же для ответа answerer-а {id: {"text"|"choice"}}; выбор не трогается."""
    out = {}
    for qid, ans in (answers or {}).items():
        if isinstance(ans, dict) and isinstance(ans.get("text"), str):
            ans = {**ans, "text": cap_answer(ans["text"], limit)}
        out[qid] = ans
    return out
