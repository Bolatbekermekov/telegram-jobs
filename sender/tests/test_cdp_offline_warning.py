"""Предупреждение о неподнятом Chrome должно покрывать ВСЕ площадки на CDP.

Оно писалось под Wellfound по живому случаю (замер 2026-08-27: площадка не
отдала ни одной вакансии за прогон, Chrome в тот день не поднимали, а наружу
выходили только сырой «connect ECONNREFUSED 127.0.0.1:9222» и «wellfound: 0 с,
ошибка» — оба читаются как поломка кода, а не как «подними окно»).

С Indeed ситуация ровно та же: замер 2026-09-12 показал, что площадка отвечает
403 всему, кроме настоящего Chrome. Оставить предупреждение привязанным к одному
имени значило бы повторить ту же немую ошибку на новой площадке.
"""
from app.application.notify import cdp_offline_message

UP = {"wellfound": True, "indeed": True}
DOWN = {"wellfound": False, "indeed": False}


def test_silence_when_every_port_is_alive():
    assert cdp_offline_message({"wellfound", "indeed", "hh"}, UP) == ""


def test_silence_when_no_cdp_platform_is_in_this_run():
    """`make search_hh` не должен платить двумя секундами за чужую проверку."""
    assert cdp_offline_message({"hh", "remoteok"}, DOWN) == ""


def test_wellfound_alone_is_named():
    note = cdp_offline_message({"wellfound", "hh"}, {"wellfound": False, "indeed": True})
    assert "Wellfound" in note and "Indeed" not in note
    assert "make login_wellfound" in note


def test_indeed_alone_is_named():
    note = cdp_offline_message({"indeed"}, {"wellfound": True, "indeed": False})
    assert "Indeed" in note and "Wellfound" not in note
    assert "make login_indeed" in note


def test_both_down_are_named_in_one_note():
    """Два предупреждения подряд человек читает как одно и пропускает второе."""
    note = cdp_offline_message({"wellfound", "indeed"}, DOWN)
    assert "Wellfound" in note and "Indeed" in note
    assert note.count("⚠️") == 1


def test_a_platform_that_is_down_but_absent_stays_silent():
    assert cdp_offline_message({"hh"}, DOWN) == ""
