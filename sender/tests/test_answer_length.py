"""Подробный ответ в анкете — но не длиннее 500 знаков.

Решение владельца 2026-09-25: отвечать подробно, но ограничить 500 знаками.
В прогоне 2026-09-24 поля «Summary» и «Cover letter» (лид #1578) получили
ответы длиннее 400 знаков — журнал в «Заметке» обрезал их именно там.

Модели это сказано в промпте, а код страхует: ответ длиннее режется по концу
последнего ЦЕЛОГО предложения — оборванная на полуслове фраза не уходит
работодателю. Выбор варианта не трогается.
"""
from types import SimpleNamespace

from app.domain.answer_length import MAX_ANSWER_CHARS, cap_answer, cap_answers

SENT = "I build production AI agents with LangGraph and FastAPI at Atlanti.ai. "


def test_the_limit_is_500():
    assert MAX_ANSWER_CHARS == 500


def test_a_short_answer_is_untouched():
    assert cap_answer("Yes, three years with Python.") == "Yes, three years with Python."


def test_a_long_answer_is_cut_at_the_last_whole_sentence():
    long = SENT * 12                      # ~840 знаков
    out = cap_answer(long)
    assert len(out) <= 500
    assert out.endswith(".")
    assert long.startswith(out)           # ничего не переписано, только обрезано


def test_one_endless_sentence_is_cut_at_a_word_and_closed():
    long = "I worked on " + ", ".join(f"service number {i}" for i in range(60))
    out = cap_answer(long)
    assert len(out) <= 500
    assert out.endswith(".")
    assert not out.endswith(",.")


def test_only_text_answers_are_capped():
    answers = {"1": {"text": SENT * 12}, "2": {"choice": 3}}
    out = cap_answers(answers)
    assert len(out["1"]["text"]) <= 500
    assert out["2"] == {"choice": 3}


def test_the_production_answerer_caps_what_it_returns(monkeypatch):
    """Сквозная проверка: answerer, которым ходят hh, LinkedIn и внешние формы,
    отдаёт уже урезанный ответ — значит и журнал в «Заметке» видит то, что
    реально ушло."""
    from app.infrastructure.channels import registry
    monkeypatch.setattr("app.infrastructure.cv_loader.load_cv_text", lambda p: "CV")
    monkeypatch.setattr("app.infrastructure.cv_loader.load_text_file", lambda p: "PROFILE")
    monkeypatch.setattr("app.infrastructure.apply_profile_loader.load_apply_profile",
                        lambda *a, **k: SimpleNamespace(is_blank=lambda: True))
    monkeypatch.setattr(
        "app.infrastructure.openai_client.OpenAIMessageGenerator.answer_questions",
        lambda self, cv, profile, vac, qs, language="": {"1": {"text": SENT * 12}})
    cfg = SimpleNamespace(LLM_API_KEY="k", LLM_MODEL="m", OPENAI_MAX_OUTPUT_TOKENS=100,
                          LLM_BASE_URL=None, CV_PATH="cv.pdf", PROFILE_PATH="p.md",
                          APPLY_PROFILE_PATH="", CONTACTS=None)
    answer = registry._hh_answerer(cfg)
    out = answer([{"id": "1", "type": "text", "prompt": "Tell us about you"}], "JOB")
    assert len(out["1"]["text"]) <= 500
