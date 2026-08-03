from app.application.run_search import run_search
from app.domain.candidate import Candidate, normalize_url


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
    def __init__(self, known=()):
        self.added = []
        self._known = {normalize_url(u) for u in known}

    def known_urls(self):
        return set(self._known)

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


def test_run_search_skips_already_known_before_scoring():
    """Known URLs are filtered out BEFORE describe/score, so no OpenAI is wasted."""
    repo = _FakeRepo(known=["https://x/dup"])
    new = Candidate("linkedin", "job", "https://x/new", "keep", "c", "", "x", "")
    dup = Candidate("linkedin", "job", "https://x/dup", "keep", "c", "", "x", "")
    s = _FakeSearcher([new, dup])
    added = run_search(["linkedin"], {"linkedin": s}, repo,
                       keywords=["junior"], location="Worldwide", limit=15,
                       scorer=_Scorer(), profile="P", threshold=60, max_jobs=10)
    assert added == 1
    assert s.described == ["https://x/new"]   # the dup was never described/scored


# --- вакансия, отвергнутая скорером, больше не оценивается --------------------
#
# Отказник не сохранялся никуда: known_urls() читает только сохранённых
# кандидатов. Каждый следующий прогон снова качал его описание и снова платил за
# скоринг — а так как порядок выдачи детерминированный, одни и те же отказники
# занимали весь бюджет, и вакансии за ними не начинались никогда.

class _FakeScoredOut:
    def __init__(self, known=()):
        self._known = set(known)
        self.saved = False

    def known(self):
        return set(self._known)

    def add(self, url):
        self._known.add(normalize_url(url))

    def save(self):
        self.saved = True


def test_a_rejected_job_is_remembered():
    store = _FakeScoredOut()
    drop = Candidate("linkedin", "job", "https://x/drop", "drop", "c", "", "x", "")
    run_search(["linkedin"], {"linkedin": _FakeSearcher([drop])}, _FakeRepo(),
               keywords=["junior"], location="Worldwide", limit=15,
               scorer=_Scorer(), profile="P", threshold=60, max_jobs=10,
               scored_out=store)

    assert "https://x/drop" in store.known()
    assert store.saved


def test_a_remembered_reject_is_never_described_again():
    store = _FakeScoredOut(known=["https://x/old"])
    old = Candidate("linkedin", "job", "https://x/old", "keep", "c", "", "x", "")
    new = Candidate("linkedin", "job", "https://x/new", "keep", "c", "", "x", "")
    s = _FakeSearcher([old, new])
    run_search(["linkedin"], {"linkedin": s}, _FakeRepo(),
               keywords=["junior"], location="Worldwide", limit=15,
               scorer=_Scorer(), profile="P", threshold=60, max_jobs=10,
               scored_out=store)

    assert s.described == ["https://x/new"]


# --- дубли ВНУТРИ одного прогона ---------------------------------------------
#
# Локации перекрываются по построению: «Worldwide» включает все страны, а
# «European Union» — Германию, Нидерланды и Польшу. Замер живого LinkedIn
# 2026-08-03 по одному слову и трём локациям: 75 карточек, 65 уникальных, то
# есть 13% дублей — и каждый занимал бы отдельный слот в бюджете скоринга.

def test_the_same_job_found_twice_is_scored_once():
    repo = _FakeRepo()
    same = "https://x/keep"
    s = _FakeSearcher([
        Candidate("linkedin", "job", same, "keep", "c", "", "x", ""),
        Candidate("linkedin", "job", same + "?utm=eu", "keep", "c", "", "x", ""),
    ])
    added = run_search(["linkedin"], {"linkedin": s}, repo,
                       keywords=["junior"], location="Worldwide", limit=15,
                       scorer=_Scorer(), profile="P", threshold=60, max_jobs=10)

    assert len(s.described) == 1
    assert added == 1


def test_deduplication_happens_even_without_a_scorer():
    """Без скоринга дубль просто уезжает в лист второй строкой."""
    repo = _FakeRepo()
    added = run_search(["linkedin"], {"linkedin": _FakeSearcher(
        [_cand("https://x/1"), _cand("https://x/1?ref=a"), _cand("https://x/2")])},
        repo, keywords=["junior"], location="Worldwide", limit=15)

    assert added == 2


# --- сколько времени ушло на площадку ----------------------------------------

def test_each_platform_reports_its_time_and_yield():
    seen = []
    searchers = {"linkedin": _FakeSearcher([_cand("https://x/1")]),
                 "wellfound": _FakeSearcher([])}
    run_search(["linkedin", "wellfound"], searchers, _FakeRepo(),
               keywords=["junior"], location="Worldwide", limit=15,
               on_platform_done=lambda p, secs, n: seen.append((p, n, secs >= 0)))

    assert seen == [("linkedin", 1, True), ("wellfound", 0, True)]


def test_a_failed_platform_is_reported_as_a_failure_not_as_an_empty_one():
    """Иначе площадка, упавшая на первой секунде, неотличима от площадки, где
    просто ничего не нашлось."""
    seen = []
    run_search(["linkedin"], {"linkedin": _FakeSearcher([], boom=True)}, _FakeRepo(),
               keywords=["junior"], location="Worldwide", limit=15,
               on_platform_done=lambda p, secs, n: seen.append((p, n)))

    assert seen == [("linkedin", None)]


def test_without_a_store_everything_still_works():
    """Память — необязательная деталь: без неё поиск обязан работать как раньше."""
    added = run_search(["linkedin"], {"linkedin": _FakeSearcher([_cand("https://x/1")])},
                       _FakeRepo(), keywords=["junior"], location="Worldwide", limit=15)
    assert added == 1
