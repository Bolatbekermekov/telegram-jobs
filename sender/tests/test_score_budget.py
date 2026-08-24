"""Бюджет скоринга считает ПРОШЕДШИХ, а не потраченные попытки.

Замер 2026-08-22, полный поиск по пяти площадкам: hh оценил 30 вакансий, 25 из
них отверг, и в таблицу попало 5. LinkedIn оценил свои 30 и не пропустил ни
одной. Оба упёрлись ровно в `max_jobs`, потому что слот тратился на КАЖДУЮ
оценку — отвергнутые съедали бюджет, и за ними прогон просто не начинался.

Теперь `max_jobs` — это сколько вакансий должно ДОЕХАТЬ до листа. Скоринг идёт
дальше по списку, пока их не наберётся столько.

Бесконечным это быть не может: одна оценка стоит скачивания описания и вызова
модели (замерено: ~19 с на LinkedIn, ~38 с на hh), а площадка, где всё ниже
порога, иначе просканировала бы всё найденное и шла бы часами. Поэтому сверху
стоит `scan_limit` — потолок на число оценок за прогон, и его срабатывание
объявляется вслух, а не проглатывается.
"""
from app.application.relevance import score_and_filter


class _Cand:
    def __init__(self, url, score):
        self.url = url
        self.title = url
        self.summary = ""
        self._score = score


class _Scorer:
    """Балл зашит в саму вакансию — тест управляет вердиктом, а не текстом."""

    def __init__(self):
        self.calls = 0

    def score(self, profile, title, description):
        self.calls += 1
        return description, "почему"


def _describe(c):
    return c._score


def _run(cands, *, max_jobs, threshold=60, scan_limit=None, on_reject=None,
         on_scan_limit=None, describe=_describe):
    scorer = _Scorer()
    kept = score_and_filter(cands, describe, scorer, "профиль", threshold, max_jobs,
                            on_reject=on_reject, scan_limit=scan_limit,
                            on_scan_limit=on_scan_limit)
    return kept, scorer


def test_rejected_vacancies_no_longer_eat_the_budget():
    """Главная регрессия: первые две ниже порога, дальше идут подходящие.
    Со старым поведением (`candidates[:max_jobs]`) результат был бы пустым."""
    cands = [_Cand("a", 10), _Cand("b", 20), _Cand("c", 90), _Cand("d", 95)]

    kept, scorer = _run(cands, max_jobs=2)

    assert [c.url for c in kept] == ["c", "d"]
    assert scorer.calls == 4          # пришлось оценить все четыре


def test_scoring_stops_as_soon_as_the_quota_is_full():
    """Лишние вызовы модели — деньги и минуты, поэтому за целью не идём."""
    cands = [_Cand(str(i), 90) for i in range(10)]

    kept, scorer = _run(cands, max_jobs=3)

    assert len(kept) == 3
    assert scorer.calls == 3


def test_the_ceiling_stops_a_platform_where_nothing_matches():
    cands = [_Cand(str(i), 10) for i in range(500)]

    kept, scorer = _run(cands, max_jobs=30, scan_limit=5)

    assert kept == []
    assert scorer.calls == 5


def test_hitting_the_ceiling_is_announced_not_swallowed():
    """Молчаливый обрез читается как «площадка пуста», а это неправда: там
    осталось непросмотренное, и в следующий прогон оно не попадёт само."""
    said = []
    cands = [_Cand(str(i), 10) for i in range(50)]

    _run(cands, max_jobs=30, scan_limit=4,
         on_scan_limit=lambda scanned, kept: said.append((scanned, kept)))

    assert said == [(4, 0)]


def test_running_out_of_vacancies_is_not_a_ceiling_event():
    """Список кончился — это норма, а не обрез, и объявлять нечего."""
    said = []

    _run([_Cand("a", 90)], max_jobs=30, scan_limit=100,
         on_scan_limit=lambda scanned, kept: said.append((scanned, kept)))

    assert said == []


def test_a_vacancy_whose_page_failed_still_costs_a_slot():
    """Иначе площадка, у которой отваливается каждое описание, крутила бы этот
    цикл по всему найденному — потолок обязан считать попытки, а не вердикты."""
    def _boom(c):
        raise RuntimeError("сеть отвалилась")

    kept, _ = _run([_Cand(str(i), 90) for i in range(50)],
                   max_jobs=30, scan_limit=3, describe=_boom)

    assert kept == []


def test_rejects_are_still_remembered():
    """Память об отказниках — то, что не даёт им занимать бюджет в следующий раз."""
    seen = []

    _run([_Cand("a", 10), _Cand("b", 90)], max_jobs=1,
         on_reject=lambda c: seen.append(c.url))

    assert seen == ["a"]


def test_no_ceiling_means_scan_until_the_quota_is_full():
    """`scan_limit=None` — прежнее поведение бюджета, только без потолка."""
    cands = [_Cand(str(i), 10) for i in range(20)] + [_Cand("good", 90)]

    kept, scorer = _run(cands, max_jobs=1, scan_limit=None)

    assert [c.url for c in kept] == ["good"]
    assert scorer.calls == 21
