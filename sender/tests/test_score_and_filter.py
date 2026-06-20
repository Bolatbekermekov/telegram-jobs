from app.application.relevance import score_and_filter
from app.domain.candidate import Candidate


def _cand(title):
    return Candidate(platform="linkedin", kind="job", url=f"https://x/{title}",
                     title=title, company="Co", salary="", location="", summary="")


class _Scorer:
    def __init__(self, mapping):
        self._m = mapping

    def score(self, profile, title, description):
        return self._m[title]


def test_keeps_only_at_or_above_threshold_and_sets_summary():
    cands = [_cand("A"), _cand("B")]
    scorer = _Scorer({"A": (80, "good fit"), "B": (30, "wrong role")})
    out = score_and_filter(cands, lambda c: "desc", scorer, "P", threshold=60, max_jobs=10)
    assert [c.title for c in out] == ["A"]
    assert out[0].summary == "80/100: good fit"


def test_caps_at_max_jobs():
    cands = [_cand("A"), _cand("B"), _cand("C")]
    scorer = _Scorer({"A": (90, "x"), "B": (90, "y")})  # C never scored
    out = score_and_filter(cands, lambda c: "d", scorer, "P", threshold=10, max_jobs=2)
    assert {c.title for c in out} == {"A", "B"}


def test_describe_failure_skips_only_that_job():
    cands = [_cand("A"), _cand("B")]
    scorer = _Scorer({"A": (90, "ok")})

    def describe(c):
        if c.title == "B":
            raise RuntimeError("page gone")
        return "desc"

    out = score_and_filter(cands, describe, scorer, "P", threshold=10, max_jobs=10)
    assert [c.title for c in out] == ["A"]
