from app.application.run_search import run_search
from app.domain.candidate import Candidate


def _cand(url, platform="linkedin"):
    return Candidate(platform=platform, kind="job", url=url, title="t", company="c",
                     salary="", location="x", summary="s")


class _FakeSearcher:
    def __init__(self, candidates, boom=False):
        self._c = candidates
        self._boom = boom
        self.started = self.stopped = False
        self.described = []

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def search(self, keywords_list, location, limit):
        if self._boom:
            raise RuntimeError("selector drift")
        return self._c

    def describe(self, url):
        self.described.append(url)
        return "desc"


class _FakeRepo:
    def __init__(self):
        self.added = []

    def add_new(self, candidates):
        items = list(candidates)
        self.added += items
        return len(items)


def test_run_search_adds_found_candidates():
    repo = _FakeRepo()
    searchers = {"linkedin": _FakeSearcher([_cand("https://x/1"), _cand("https://x/2")])}
    added = run_search(["linkedin"], searchers, repo,
                       keywords=["junior"], location="Worldwide", limit=15)
    assert added == 2 and len(repo.added) == 2
    assert searchers["linkedin"].started and searchers["linkedin"].stopped


def test_run_search_survives_one_platform_failing():
    repo = _FakeRepo()
    searchers = {
        "linkedin": _FakeSearcher([], boom=True),
        "wellfound": _FakeSearcher([_cand("https://w/1", "wellfound")]),
    }
    added = run_search(["linkedin", "wellfound"], searchers, repo,
                       keywords=["junior"], location="Worldwide", limit=15)
    assert added == 1               # wellfound still ran
    assert searchers["wellfound"].stopped
    assert searchers["linkedin"].stopped   # stop() always called


class _Scorer:
    def score(self, profile, title, description):
        # keep only the candidate whose url ends in /keep
        return (90, "fit") if description and title == "keep" else (10, "no")


def test_run_search_with_scorer_filters_and_describes():
    repo = _FakeRepo()
    keep = Candidate("linkedin", "job", "https://x/keep", "keep", "c", "", "x", "")
    drop = Candidate("linkedin", "job", "https://x/drop", "drop", "c", "", "x", "")
    s = _FakeSearcher([keep, drop])
    added = run_search(["linkedin"], {"linkedin": s}, repo,
                       keywords=["junior"], location="Worldwide", limit=15,
                       scorer=_Scorer(), profile="P", threshold=60, max_jobs=10)
    assert added == 1
    assert [c.title for c in repo.added] == ["keep"]
    assert s.described  # descriptions were fetched for scoring
