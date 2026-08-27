from app.application.relevance import score_and_filter
from app.domain.candidate import Candidate


def _cand(title, location=""):
    return Candidate(platform="linkedin", kind="job", url=f"https://x/{title}",
                     title=title, company="Co", salary="", location=location,
                     summary="")


class _Scorer:
    def __init__(self, mapping):
        self._m = mapping
        self.seen = []

    def score(self, profile, title, description, location=""):
        self.seen.append((title, location))
        return self._m[title]


def test_the_candidates_location_is_handed_to_the_scorer():
    """Страну вакансии знает только кандидат — площадка кладёт её в
    `Candidate.location`, а не в описание. Пока `score_and_filter` её не
    передавал, полстраницы профиля про право на работу и спонсорство визы
    модель применяла к тексту, где страны может не быть вовсе."""
    scorer = _Scorer({"A": (80, "fit")})
    score_and_filter([_cand("A", "🇰🇿 Kazakhstan")], lambda c: "desc", scorer,
                     "P", threshold=60, max_jobs=10)
    assert scorer.seen == [("A", "🇰🇿 Kazakhstan")]


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


def test_a_rejected_job_is_reported_so_it_is_never_scored_again():
    """Отвергнутая вакансия не сохранялась НИКУДА, а порядок выдачи
    детерминированный — значит одни и те же отказники занимали весь бюджет
    скоринга в каждом прогоне, и вакансии за ними не начинались никогда."""
    rejected = []
    cands = [_cand("A"), _cand("B")]
    scorer = _Scorer({"A": (80, "good"), "B": (30, "wrong role")})
    score_and_filter(cands, lambda c: "d", scorer, "P", threshold=60, max_jobs=10,
                     on_reject=lambda c: rejected.append(c.url))

    assert rejected == ["https://x/B"]


def test_a_job_we_could_not_read_is_not_written_off():
    """Описание не загрузилось — это про сеть, а не про вакансию. Запомнить её
    как отвергнутую значит потерять её навсегда из-за одного таймаута."""
    rejected = []
    cands = [_cand("A")]

    def describe(c):
        raise RuntimeError("page gone")

    score_and_filter(cands, describe, _Scorer({}), "P", threshold=60, max_jobs=10,
                     on_reject=lambda c: rejected.append(c.url))

    assert rejected == []


def test_describe_failure_skips_only_that_job():
    cands = [_cand("A"), _cand("B")]
    scorer = _Scorer({"A": (90, "ok")})

    def describe(c):
        if c.title == "B":
            raise RuntimeError("page gone")
        return "desc"

    out = score_and_filter(cands, describe, scorer, "P", threshold=10, max_jobs=10)
    assert [c.title for c in out] == ["A"]
