"""Где стоит проверка права на работу — в поиске до оценки и в прогоне до письма.

Поиск: невыполнимая вакансия не должна стоить вызова модели и не должна
попасть в лист. Её запоминают как отказника, чтобы следующий прогон не качал
описание снова.

Прогон: лид из интейка оценки не проходил вовсе, поэтому калитка нужна и
перед генерацией письма. Статус — `manual`, НЕ `skipped`: владелец запретил
автоматически закрывать лиды (см. `dead_vacancy_reason`), и человек должен
увидеть причину и решить сам.
"""
from app.application.relevance import score_and_filter
from app.application.send_plan import ineligible_reason
from app.domain.candidate import Candidate
from app.domain.eligibility import check_eligibility
from app.domain.lead import STATUS_MANUAL, Lead

HOME = "Kazakhstan"


def _lead(raw, vacancy=""):
    return Lead(row=2, lead_id="1516", platform="email", target="hr@x.test",
                vacancy_context=vacancy, raw_text=raw, status="new")


# --- прогон ---

def test_an_ineligible_lead_goes_to_manual_with_the_reason():
    lead = _lead("Full-Stack Developer, remote. Open exclusively to Pakistani candidates.")
    status, note = ineligible_reason(lead, HOME)
    assert status == STATUS_MANUAL
    assert "Pakistan" in note


def test_an_eligible_lead_passes():
    assert ineligible_reason(_lead("Python developer, remote worldwide."), HOME) is None


def test_the_location_line_of_a_search_lead_is_read():
    """Поиск пишет страну строкой «Локация: …» в текст вакансии — без неё
    «визу не спонсируем» не с чем сопоставить."""
    lead = _lead("Backend Engineer — Acme\nЛокация: Berlin, Germany (On-site)\n"
                 "We are unable to sponsor visas.")
    assert ineligible_reason(lead, HOME) is not None


def test_without_a_home_country_nothing_is_blocked():
    """Пустая анкета — не повод считать чужой любую страну."""
    lead = _lead("Open exclusively to Pakistani candidates.")
    assert ineligible_reason(lead, "") is None


# --- поиск ---

def _cand(title, location=""):
    return Candidate(platform="linkedin", kind="job", url=f"https://x/{title}",
                     title=title, company="Co", salary="", location=location,
                     summary="")


class _Scorer:
    def __init__(self):
        self.seen = []

    def score(self, profile, title, description, location=""):
        self.seen.append(title)
        return 80, "fit"


def _eligibility(description, location):
    return check_eligibility(description, location=location, home_country=HOME)


def test_an_ineligible_job_is_never_scored_and_is_remembered():
    scorer, rejected, told = _Scorer(), [], []
    descriptions = {"A": "Remote, worldwide.", "B": "US-based candidates only."}
    kept = score_and_filter(
        [_cand("A"), _cand("B")], lambda c: descriptions[c.title], scorer, "P",
        threshold=60, max_jobs=10, on_reject=lambda c: rejected.append(c.title),
        eligibility=_eligibility,
        on_ineligible=lambda c, verdict: told.append((c.title, verdict.blocking_reasons)))
    assert [c.title for c in kept] == ["A"]
    assert scorer.seen == ["A"]
    assert rejected == ["B"]
    assert told and told[0][0] == "B" and told[0][1]


def test_the_candidates_location_reaches_the_check():
    scorer = _Scorer()
    kept = score_and_filter(
        [_cand("A", "Berlin, Germany (On-site)")],
        lambda c: "We do not offer visa sponsorship.", scorer, "P",
        threshold=60, max_jobs=10, eligibility=_eligibility)
    assert kept == [] and scorer.seen == []


def test_without_the_check_everything_is_scored_as_before():
    scorer = _Scorer()
    kept = score_and_filter([_cand("B")], lambda c: "US-based candidates only.",
                            scorer, "P", threshold=60, max_jobs=10)
    assert [c.title for c in kept] == ["B"]


def test_run_search_hands_the_check_to_the_scoring_loop():
    """Проверка настраивается в `_relevance_args` и едет в `run_search` теми же
    kwargs, что скорер, — сам `run_search` должен донести её до цикла оценки."""
    from app.application.run_search import run_search

    class _Searcher:
        def start(self): pass
        def stop(self): pass
        def search(self, keywords, location, limit):
            return [_cand("A"), _cand("B")]
        def describe(self, url):
            return "US-based candidates only." if url.endswith("/B") else "Remote."

    class _Repo:
        def __init__(self): self.added = []
        def known_urls(self): return set()
        def add_new(self, cands):
            self.added += list(cands)
            return len(self.added)

    repo, told = _Repo(), []
    run_search(["linkedin"], {"linkedin": _Searcher()}, repo, keywords=["ai"],
               location="", limit=10, scorer=_Scorer(), profile="P", threshold=60,
               max_jobs=10, eligibility=_eligibility,
               on_ineligible=lambda c, v: told.append(c.title))
    assert [c.title for c in repo.added] == ["A"]
    assert told == ["B"]


def test_our_own_model_verdict_is_not_the_employers_requirement():
    """Живьём 2026-09-24, лид #1591 (RemoteHunter): в описании ни слова о визе
    и праве на работу, а модель по одной локации «United States (Remote)»
    написала в причине оценки «удаленка только для США без визовой поддержки».
    Поиск кладёт эту причину строкой «75/100: …» в текст вакансии, и калитка
    прогона приняла догадку модели за требование работодателя. Блокирует только
    то, что написал работодатель."""
    lead = _lead("Mid-Level Backend Engineer — RemoteHunter\n"
                 "Локация: United States (Remote)\n"
                 "75/100: Роль Backend Engineer подходит (уровень Mid), но удаленка "
                 "только для США без визовой поддержки.")
    assert ineligible_reason(lead, HOME) is None


def test_an_old_style_verdict_on_the_title_line_is_ignored_too():
    """Старые строки клеили оценку к названию: «Title — 82/100: …»."""
    lead = _lead("Junior AI Engineer — 82/100: entry-level, remote UK-only "
                 "(нужно право на работу в UK)")
    assert ineligible_reason(lead, HOME) is None
