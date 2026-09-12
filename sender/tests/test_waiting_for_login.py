"""Площадка без сессии не должна ронять прогон, если сессия ей НЕОБЯЗАТЕЛЬНА.

Обычное правило прогона жёсткое и правильное: канал, который не поднялся, — это
сломанная настройка, и прогон останавливается целиком (`cli.py`, обработчик
`for_platform`). Иначе протухшая сессия hh тихо съедала бы очередь, пока
здоровые площадки её дренируют.

Но у части площадок сессия нужна только для ОТКЛИКА, а поиск идёт анонимно, и
появиться она может нескоро или никогда. У Threads это уже решено отдельным
гейтом до открытия канала (`dm_fallback_reason`). Jobicy — ровно тот же случай:
лента отдаётся по открытому API без аккаунта, а кнопка «Apply Now» — гейт
регистрации (замер 2026-09-11).

Без этого правила тринадцать лидов Jobicy, найденных поиском, убили бы следующий
прогон на первом же из них — вместе с hh, телеграмом и всем, что стояло в
очереди после.
"""
from app.application.send_plan import waiting_for_login


def test_jobicy_without_a_session_waits():
    note = waiting_for_login("jobicy", session_exists=False)
    assert note is not None
    assert "login_jobicy" in note, "человеку нужно имя чинящей команды, а не факт"


def test_jobicy_with_a_session_goes_through_the_normal_path():
    assert waiting_for_login("jobicy", session_exists=True) is None


def test_a_platform_whose_session_must_work_still_stops_the_run():
    """hh, LinkedIn, Wellfound: там мёртвая сессия — это поломка, а не ожидание.

    Тихо пропустить их лиды значило бы дренировать очередь здоровых площадок,
    пока сломанная остаётся незамеченной.
    """
    for platform in ("hh", "linkedin", "wellfound", "remoteok", "telegram"):
        assert waiting_for_login(platform, session_exists=False) is None


def test_an_unknown_platform_is_not_special_cased():
    assert waiting_for_login("совсем-новая", session_exists=False) is None
