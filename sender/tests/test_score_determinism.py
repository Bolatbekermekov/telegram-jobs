"""Оценка вакансии воспроизводима, а сбой разбора — не приговор вакансии.

Замер 2026-08-28: одиннадцать побайтно одинаковых копий одного объявления
получили в одном прогоне 74, 78, 78, 78, 80, 82, 82, 82, 83, 84, 88. Причина —
`temperature` не задавалась нигде, и модель работала на 1.0. Порог и любая
сортировка по такому баллу случайны ровно настолько же.

Второе: неразобранный ответ модели превращался в балл 0, а ноль ниже порога
уходил в память отказников — вакансия списывалась НАВСЕГДА из-за сбоя формата,
а не из-за вердикта о ней.
"""
import httpx
import pytest
from openai import BadRequestError

from app.application.relevance import parse_score_response, score_and_filter
from app.domain.candidate import Candidate
from app.infrastructure.openai_relevance import OpenAIRelevanceScorer


def _reply(content):
    msg = type("M", (), {"content": content})()
    return type("R", (), {"choices": [type("Ch", (), {"message": msg})()]})()


def _scorer_with(monkeypatch, create):
    scorer = OpenAIRelevanceScorer("k", "m")
    completions = type("Co", (), {"create": staticmethod(create)})()
    monkeypatch.setattr(scorer, "_client", type("C", (), {
        "chat": type("Ch", (), {"completions": completions})()})())
    return scorer


def _400(message):
    return BadRequestError(message, response=httpx.Response(
        400, request=httpx.Request("POST", "https://example.test")), body=None)


# --- воспроизводимость ---

def test_the_score_is_asked_for_at_zero_temperature(monkeypatch):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return _reply('{"score": 75, "reason": "ok"}')

    _scorer_with(monkeypatch, create).score("P", "AI Engineer", "desc")
    assert calls[0].get("temperature") == 0


def test_a_model_that_refuses_temperature_is_asked_again_without_it(monkeypatch):
    """Рассуждающие модели OpenAI (gpt-5.x) принимают только temperature=1 и
    отвечают 400. Потерять из-за этого оценку нельзя: провайдер переключается
    одной переменной окружения, и поиск не должен от неё сломаться."""
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        if "temperature" in kwargs:
            raise _400("Unsupported value: 'temperature' does not support 0 "
                       "with this model. Only the default (1) value is supported.")
        return _reply('{"score": 75, "reason": "ok"}')

    scorer = _scorer_with(monkeypatch, create)
    assert scorer.score("P", "AI Engineer", "desc") == (75, "ok")
    # Второй раз модель уже не дёргаем с заведомо отвергнутым параметром.
    scorer.score("P", "AI Engineer", "desc")
    assert [("temperature" in c) for c in calls] == [True, False, False]


def test_an_unrelated_bad_request_is_not_swallowed(monkeypatch):
    def create(**kwargs):
        raise _400("context length exceeded")

    with pytest.raises(BadRequestError):
        _scorer_with(monkeypatch, create).score("P", "AI Engineer", "desc")


# --- сбой разбора ≠ балл 0 ---

@pytest.mark.parametrize("raw", [
    "not json at all",
    '{"reason": "без балла"}',
    '{"score": "высокий", "reason": "x"}',
    "",
])
def test_an_unreadable_answer_is_an_error_not_a_zero(raw):
    with pytest.raises(ValueError):
        parse_score_response(raw)


def test_an_unreadable_answer_does_not_write_the_vacancy_off(monkeypatch):
    """Вся цепочка: модель ответила прозой -> вакансия не оценена и НЕ попадает в
    память отказников, то есть следующий прогон оценит её снова."""
    scorer = _scorer_with(monkeypatch, lambda **kw: _reply("Я думаю, подходит."))
    cand = Candidate(platform="linkedin", kind="job", url="https://x/A", title="A",
                     company="Co", salary="", location="", summary="")
    rejected = []
    kept = score_and_filter([cand], lambda c: "desc", scorer, "P", threshold=60,
                            max_jobs=10, on_reject=lambda c: rejected.append(c.url))
    assert kept == [] and rejected == []
