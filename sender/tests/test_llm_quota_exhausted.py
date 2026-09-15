"""Дневная квота модели кончилась — оценка поиска останавливается сразу.

Живьём 2026-09-15: поиск AI Engineer простоял ночь (00:40–08:40) на LinkedIn и
не записал ничего. Бесплатный Gemini израсходовал дневную квоту
gemini-3.5-flash-lite (500 запросов) ещё накануне, а в отказе написал «Please
retry in 24.96s» — и `with_rate_limit_retry` честно ждал названные секунды по три
раза на КАЖДОЙ из 169 вакансий, после чего `score_and_filter` списывал сбой на
одну вакансию и брался за следующую. Отличие от поминутного лимита видно только
в `quotaId`: `…PerDay…` вместо `…PerMinute…`. Суточное окно за минуту не
откроется, поэтому прогон обязан остановить оценку, записать уже отобранное и
сказать, чего не просмотрел.
"""
import httpx
import pytest
from openai import RateLimitError

from app.application.notify import quota_stop_message
from app.application.relevance import score_and_filter
from app.application.run_search import run_search
from app.domain.candidate import Candidate
from app.domain.llm_quota import LLMQuotaExhausted, exhausted_quota_note
from app.infrastructure.rate_limit import with_rate_limit_retry

# Отказ Gemini 2026-09-15: сообщение и violations из одного ответа, ссылки срезаны.
GEMINI_DAY_429 = (
    "Error code: 429 - [{'error': {'code': 429, 'message': 'You exceeded your current "
    "quota, please check your plan and billing details. \\n* Quota exceeded for metric: "
    "generativelanguage.googleapis.com/generate_content_free_tier_requests, limit: 500, "
    "model: gemini-3.5-flash-lite\\nPlease retry in 24.960235557s.', 'status': "
    "'RESOURCE_EXHAUSTED', 'details': [{'@type': 'type.googleapis.com/google.rpc.QuotaFailure', "
    "'violations': [{'quotaMetric': 'generativelanguage.googleapis.com/"
    "generate_content_free_tier_requests', 'quotaId': "
    "'GenerateRequestsPerDayPerProjectPerModel-FreeTier', 'quotaDimensions': {'location': "
    "'global', 'model': 'gemini-3.5-flash-lite'}, 'quotaValue': '500'}]}, {'@type': "
    "'type.googleapis.com/google.rpc.RetryInfo', 'retryDelay': '40s'}]}}]")

# Поминутный отказ (замер 2026-09-07, как в test_rate_limit_retry) — его пережидаем.
GEMINI_MINUTE_429 = (
    "Error code: 429 - You exceeded your current quota. "
    "* Quota exceeded for metric: generate_content_free_tier_requests, "
    "limit: 20, model: gemini-3.5-flash\nPlease retry in 52.52279s")

# Тот же поминутный отказ с полным `details`, по образцу дневного выше.
GEMINI_MINUTE_429_WITH_ID = (
    "Error code: 429 - [{'error': {'code': 429, 'message': 'You exceeded your current "
    "quota. \\n* Quota exceeded for metric: generate_content_free_tier_requests, limit: 15, "
    "model: gemini-3.5-flash-lite\\nPlease retry in 12.5s.', 'details': [{'violations': "
    "[{'quotaId': 'GenerateRequestsPerMinutePerProjectPerModel-FreeTier', "
    "'quotaValue': '15'}]}]}}]")

# OpenAI, у ключа кончился баланс: тоже 429, и тоже не пройдёт за минуту.
OPENAI_BALANCE_429 = (
    "Error code: 429 - {'error': {'message': 'You exceeded your current quota, please "
    "check your plan and billing details.', 'type': 'insufficient_quota', 'param': None, "
    "'code': 'insufficient_quota'}}")


def _429(message):
    return RateLimitError(message, response=httpx.Response(
        429, request=httpx.Request("POST", "https://example.test")), body=None)


# --- что считать исчерпанной квотой ---

def test_a_daily_quota_is_named_with_its_model_and_size():
    note = exhausted_quota_note(GEMINI_DAY_429)
    assert note is not None
    assert "gemini-3.5-flash-lite" in note and "500" in note


def test_a_spent_balance_is_an_exhausted_quota_too():
    assert exhausted_quota_note(OPENAI_BALANCE_429)


@pytest.mark.parametrize("text", [GEMINI_MINUTE_429, GEMINI_MINUTE_429_WITH_ID, "quota", ""])
def test_a_per_minute_limit_is_not_an_exhausted_quota(text):
    assert exhausted_quota_note(text) is None


# --- ретрай не пережидает то, что за минуту не пройдёт ---

def test_the_retry_does_not_wait_out_a_daily_quota():
    slept, calls = [], []

    def spent():
        calls.append(1)
        raise _429(GEMINI_DAY_429)

    with pytest.raises(LLMQuotaExhausted) as err:
        with_rate_limit_retry(spent, sleep=slept.append)
    assert (len(calls), slept) == (1, [])
    assert "gemini-3.5-flash-lite" in str(err.value)


def test_a_per_minute_limit_is_still_waited_out():
    slept, calls = [], []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise _429(GEMINI_MINUTE_429_WITH_ID)
        return "ok"

    assert with_rate_limit_retry(flaky, sleep=slept.append) == "ok"
    assert len(slept) == 1


def test_the_relevance_scorer_reports_the_exhausted_quota(monkeypatch):
    from app.infrastructure.openai_relevance import OpenAIRelevanceScorer

    def no_sleep(seconds):
        raise AssertionError(f"ждал {seconds} с дневную квоту")

    monkeypatch.setattr("app.infrastructure.rate_limit.time.sleep", no_sleep)

    class _Completions:
        def create(self, **kwargs):
            raise _429(GEMINI_DAY_429)

    scorer = OpenAIRelevanceScorer("k", "m")
    monkeypatch.setattr(scorer, "_client", type("C", (), {
        "chat": type("Ch", (), {"completions": _Completions()})()})())
    with pytest.raises(LLMQuotaExhausted):
        scorer.score("P", "AI Engineer", "desc")


# --- оценка останавливается, отобранное не теряется ---

def _cand(title, platform="linkedin"):
    return Candidate(platform=platform, kind="job", url=f"https://x/{platform}/{title}",
                     title=title, company=f"Co {title}", salary="", location="",
                     summary="")


class _QuotaScorer:
    """Оценивает первые `budget` вакансий, дальше — отказ по дневной квоте."""

    def __init__(self, budget):
        self.budget = budget
        self.calls = 0

    def score(self, profile, title, description, location=""):
        self.calls += 1
        if self.calls > self.budget:
            raise LLMQuotaExhausted("дневная квота gemini-3.5-flash-lite (500) исчерпана")
        return 80, "fit"


def test_scoring_stops_at_the_exhausted_quota_and_keeps_what_passed():
    described, stops = [], []
    out = score_and_filter(
        [_cand("A"), _cand("B"), _cand("C")],
        lambda c: described.append(c.title) or "desc",
        _QuotaScorer(budget=1), "P", threshold=60, max_jobs=10,
        on_quota_exhausted=lambda exc, scored, kept: stops.append((scored, kept)))

    assert [c.title for c in out] == ["A"]
    assert described == ["A", "B"]      # C не качали: оценить её уже нечем
    assert stops == [(1, 1)]


def test_an_exhausted_quota_is_not_a_verdict_on_the_job():
    rejected = []
    score_and_filter([_cand("A")], lambda c: "desc", _QuotaScorer(budget=0), "P",
                     threshold=60, max_jobs=10,
                     on_reject=lambda c: rejected.append(c.url),
                     on_quota_exhausted=lambda *args: None)
    assert rejected == []


def test_without_a_listener_the_exhaustion_is_not_swallowed():
    with pytest.raises(LLMQuotaExhausted):
        score_and_filter([_cand("A"), _cand("B")], lambda c: "desc",
                         _QuotaScorer(budget=0), "P", threshold=60, max_jobs=10)


class _Searcher:
    def __init__(self, candidates):
        self._c = candidates
        self.started = self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def search(self, keywords, location, limit):
        return self._c

    def describe(self, url):
        return "desc"


class _Repo:
    def __init__(self):
        self.added = []

    def known_urls(self):
        return set()

    def add_new(self, candidates):
        items = list(candidates)
        self.added += items
        return len(items)


class _ScoredOut:
    def __init__(self):
        self.saved = False

    def known(self):
        return set()

    def add(self, url):
        pass

    def save(self):
        self.saved = True


def test_the_search_writes_what_passed_and_does_not_open_the_rest():
    searchers = {"linkedin": _Searcher([_cand("A"), _cand("B")]),
                 "wellfound": _Searcher([_cand("W", "wellfound")]),
                 "hh": _Searcher([_cand("H", "hh")])}
    repo, memory, stops, done = _Repo(), _ScoredOut(), [], []

    added = run_search(
        ["linkedin", "wellfound", "hh"], searchers, repo,
        keywords=["ai engineer"], location="", limit=10,
        scorer=_QuotaScorer(budget=1), profile="P", threshold=60, max_jobs=10,
        scored_out=memory,
        on_platform_done=lambda p, secs, n: done.append((p, n)),
        on_quota_exhausted=lambda p, exc, rest: stops.append((p, rest)))

    assert added == 1 and [c.title for c in repo.added] == ["A"]
    assert stops == [("linkedin", ["wellfound", "hh"])]
    assert done == [("linkedin", 1)]
    assert searchers["linkedin"].stopped
    assert not searchers["wellfound"].started and not searchers["hh"].started
    assert memory.saved


def test_without_a_listener_the_stop_is_still_reported():
    errors = []
    searchers = {"linkedin": _Searcher([_cand("A")]), "hh": _Searcher([_cand("H", "hh")])}
    run_search(["linkedin", "hh"], searchers, _Repo(), keywords=["ai"], location="",
               limit=10, scorer=_QuotaScorer(budget=0), profile="P", threshold=60,
               max_jobs=10, on_error=lambda p, e: errors.append((p, type(e))))
    assert errors == [("linkedin", LLMQuotaExhausted)]
    assert not searchers["hh"].started


# --- что услышит человек ---

def test_the_stop_message_names_the_reason_and_what_was_not_searched():
    msg = quota_stop_message(
        "linkedin", "дневная квота gemini-3.5-flash-lite (500 запросов) исчерпана",
        ["wellfound", "hh"])
    assert "linkedin" in msg and "gemini-3.5-flash-lite" in msg
    assert "wellfound, hh" in msg


def test_on_the_last_platform_there_is_no_empty_list():
    assert "не искал" not in quota_stop_message("hh", "квота исчерпана", []).lower()
