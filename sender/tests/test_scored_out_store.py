"""Память о вакансиях, которые скорер уже отверг.

Дыра, найденная 2026-08-03: отвергнутая вакансия не записывалась НИКУДА.
`known_urls()` читает только сохранённых кандидатов, поэтому каждый следующий
прогон снова качал описание той же вакансии и снова платил за скоринг. Хуже
того, порядок выдачи детерминированный — значит одни и те же отказники
занимали весь бюджет скоринга, и свежие вакансии за ними не начинались никогда.

При трёх автопрогонах в день и потолке 30 на платформу это сотни повторных
вызовов модели в сутки.
"""
from app.infrastructure.scored_out_store import ScoredOutStore


def test_a_rejected_url_is_remembered_across_runs(tmp_path):
    path = tmp_path / "scored_out.json"
    store = ScoredOutStore(str(path))
    store.add("https://www.linkedin.com/jobs/view/123/")
    store.save()

    assert ("https://www.linkedin.com/jobs/view/123"
            in ScoredOutStore(str(path)).known())


def test_urls_are_normalised_so_tracking_tails_do_not_hide_a_repeat(tmp_path):
    """Та же вакансия приходит то с utm-хвостом, то без — без приведения к
    одному виду память бесполезна."""
    store = ScoredOutStore(str(tmp_path / "s.json"))
    store.add("https://www.linkedin.com/jobs/view/123/?refId=abc&trk=x")

    assert "https://www.linkedin.com/jobs/view/123" in store.known()


def test_a_missing_file_is_simply_an_empty_memory(tmp_path):
    assert ScoredOutStore(str(tmp_path / "нет.json")).known() == set()


def test_a_corrupt_file_does_not_break_the_run(tmp_path):
    """Забыть отказников не страшно — они просто переоценятся. Уронить прогон
    из-за битого кэша страшно."""
    path = tmp_path / "s.json"
    path.write_text("{это не json", encoding="utf-8")
    assert ScoredOutStore(str(path)).known() == set()


def test_the_memory_is_bounded(tmp_path):
    """Файл не должен расти вечно: сотни отказников в день за год превратятся
    в мегабайты, которые читаются на каждом прогоне."""
    path = tmp_path / "s.json"
    store = ScoredOutStore(str(path), max_urls=10)
    for i in range(25):
        store.add(f"https://x.tld/jobs/{i}")
    store.save()

    kept = ScoredOutStore(str(path), max_urls=10).known()
    assert len(kept) == 10
    assert "https://x.tld/jobs/24" in kept        # свежие остаются
    assert "https://x.tld/jobs/0" not in kept     # самые старые вытесняются


def test_saving_nothing_new_does_not_create_a_file(tmp_path):
    path = tmp_path / "s.json"
    ScoredOutStore(str(path)).save()
    assert not path.exists()
