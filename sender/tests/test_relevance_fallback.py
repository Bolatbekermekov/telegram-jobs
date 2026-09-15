"""Оценка поиска переживает дневную квоту Gemini: запасная модель — NVIDIA.

Решение владельца 2026-09-15: «только для поиска с моделью nvidia, когда у gemini
лимит происходит … но всё равно gemini держать в приоритете». Утром того дня
поиск AI Engineer дважды упёрся в дневную квоту — у gemini-3.5-flash-lite 500
запросов в сутки, у flash всего 20, — и до сброса в 12:00 по Астане оценивать
вакансии было нечем.

Приоритет Gemini держат два правила. Каждый прогон начинает с него. А перейдя на
запасную, прогон раз в `retry_primary_after` секунд снова пробует Gemini, так что
длинный поиск, переживший сброс квоты, возвращается к нему сам. Письма и ответы
форм запасную модель не видят: она подключена только к оценке вакансий.
"""
import importlib

import pytest

from app.application.relevance_fallback import FallbackScorer
from app.domain.llm_quota import LLMQuotaExhausted
from app.llm_provider import LLMSettings

SPARE = "nvidia z-ai/glm-5.3-flash"


class _Scorer:
    def __init__(self, name, exhausted=False):
        self.name = name
        self.exhausted = exhausted
        self.calls = []

    def score(self, profile, title, description, location=""):
        self.calls.append(title)
        if self.exhausted:
            raise LLMQuotaExhausted(f"дневная квота {self.name} исчерпана")
        return 70, self.name


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def _fallback(primary, spare, clock=None, notices=None):
    return FallbackScorer(primary, spare, fallback_name=SPARE,
                          on_notice=None if notices is None else notices.append,
                          retry_primary_after=900, clock=clock or _Clock())


def test_gemini_scores_while_it_has_quota():
    gemini, nvidia = _Scorer("gemini"), _Scorer("nvidia")
    assert _fallback(gemini, nvidia).score("P", "A", "d") == (70, "gemini")
    assert nvidia.calls == []


def test_the_vacancy_that_hit_the_quota_is_scored_by_the_spare():
    gemini, nvidia = _Scorer("gemini", exhausted=True), _Scorer("nvidia")
    notices = []

    assert _fallback(gemini, nvidia, notices=notices).score("P", "A", "d") == (70, "nvidia")
    assert nvidia.calls == ["A"]
    assert len(notices) == 1
    assert SPARE in notices[0] and "gemini" in notices[0]   # куда ушли и почему


def test_after_the_switch_gemini_is_not_asked_on_every_vacancy():
    gemini, nvidia = _Scorer("gemini", exhausted=True), _Scorer("nvidia")
    clock = _Clock()
    scorer = _fallback(gemini, nvidia, clock=clock)
    for title in ("A", "B", "C"):
        clock.now += 60
        scorer.score("P", title, "d")
    assert gemini.calls == ["A"]
    assert nvidia.calls == ["A", "B", "C"]


def test_gemini_takes_over_again_once_its_quota_is_back():
    gemini, nvidia = _Scorer("gemini", exhausted=True), _Scorer("nvidia")
    clock, notices = _Clock(), []
    scorer = _fallback(gemini, nvidia, clock=clock, notices=notices)
    scorer.score("P", "A", "d")                              # квота кончилась

    clock.now = 899
    assert scorer.score("P", "B", "d") == (70, "nvidia")     # проверять рано
    gemini.exhausted = False                                 # сброс квоты
    clock.now = 900
    assert scorer.score("P", "C", "d") == (70, "gemini")
    clock.now = 901
    assert scorer.score("P", "D", "d") == (70, "gemini")

    assert gemini.calls == ["A", "C", "D"]
    assert nvidia.calls == ["A", "B"]
    assert len(notices) == 2                                 # ушли и вернулись


def test_a_still_spent_gemini_waits_another_interval_silently():
    gemini, nvidia = _Scorer("gemini", exhausted=True), _Scorer("nvidia")
    clock, notices = _Clock(), []
    scorer = _fallback(gemini, nvidia, clock=clock, notices=notices)
    scorer.score("P", "A", "d")
    clock.now = 900
    scorer.score("P", "B", "d")          # проверили — квоты всё ещё нет
    clock.now = 1799
    scorer.score("P", "C", "d")          # до следующей проверки Gemini не трогаем

    assert gemini.calls == ["A", "B"]
    assert nvidia.calls == ["A", "B", "C"]
    assert len(notices) == 1             # неудачная проверка раз в 15 минут не шумит


def test_when_the_spare_is_spent_too_the_search_stops():
    gemini = _Scorer("gemini", exhausted=True)
    nvidia = _Scorer("nvidia", exhausted=True)
    with pytest.raises(LLMQuotaExhausted) as err:
        _fallback(gemini, nvidia).score("P", "A", "d")
    assert "nvidia" in str(err.value)


def test_other_gemini_errors_do_not_switch_models():
    class _Broken(_Scorer):
        def score(self, *args, **kwargs):
            raise RuntimeError("502 Bad Gateway")

    nvidia = _Scorer("nvidia")
    with pytest.raises(RuntimeError):
        _fallback(_Broken("gemini"), nvidia).score("P", "A", "d")
    assert nvidia.calls == []


# --- откуда берётся запасная модель ---

@pytest.fixture
def reloaded(monkeypatch):
    """Перечитать конфиг с подменённым окружением и вернуть всё как было."""
    from app import config as config_module

    def _load(**env):
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        return importlib.reload(config_module)
    yield _load
    monkeypatch.undo()
    importlib.reload(config_module)


def test_the_search_fallback_has_its_own_variable(reloaded):
    cfg = reloaded(SEARCH_FALLBACK_LLM_PROVIDER="nvidia", NVIDIA_API_KEY="nvapi-test")
    assert cfg.SEARCH_FALLBACK_LLM.base_url == "https://integrate.api.nvidia.com/v1"
    assert cfg.SEARCH_FALLBACK_LLM.api_key == "nvapi-test"


def test_no_fallback_when_the_variable_is_empty(reloaded):
    assert reloaded(SEARCH_FALLBACK_LLM_PROVIDER="").SEARCH_FALLBACK_LLM is None


def test_the_fallback_leaves_the_writing_model_on_gemini(reloaded):
    cfg = reloaded(SENDER_LLM_PROVIDER="gemini", GEMINI_API_KEY="g-test",
                   SEARCH_FALLBACK_LLM_PROVIDER="nvidia", NVIDIA_API_KEY="nvapi-test")
    assert cfg.LLM_BASE_URL == "https://generativelanguage.googleapis.com/v1beta/openai"
    assert cfg.LLM_API_KEY == "g-test"


def test_the_search_scorer_gets_the_spare_only_when_configured(monkeypatch, tmp_path):
    from app.interface import cli

    profile = tmp_path / "profile.txt"
    profile.write_text("P")
    monkeypatch.setattr(cli.config, "RELEVANCE_ENABLED", True)
    monkeypatch.setattr(cli.config, "SEARCH_PROFILE_PATH", str(profile))

    monkeypatch.setattr(cli.config, "SEARCH_FALLBACK_LLM", None)
    assert not isinstance(cli._relevance_args()["scorer"], FallbackScorer)

    monkeypatch.setattr(cli.config, "SEARCH_FALLBACK_LLM_PROVIDER", "nvidia")
    monkeypatch.setattr(cli.config, "SEARCH_FALLBACK_LLM", LLMSettings(
        "nvapi-test", "https://integrate.api.nvidia.com/v1",
        "z-ai/glm-5.3-flash", "z-ai/glm-5.3-flash"))
    assert isinstance(cli._relevance_args()["scorer"], FallbackScorer)
