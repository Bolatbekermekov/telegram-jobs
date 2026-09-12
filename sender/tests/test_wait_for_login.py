"""Вход не должен требовать нажатия Enter: он должен САМ увидеть, что мы вошли.

Живьём 2026-09-11: `make login_jobicy`, запущенный без терминала на вводе (а так
его запускает и Claude Code через `!`, и любой неинтерактивный вызов), падает на
`input()` с `EOFError` ещё до того, как человек успеет войти в открывшемся окне.
Окно при этом остаётся висеть, а сессия не сохраняется.

Опрос страницы вместо ожидания клавиши чинит это целиком и заодно убирает
ловушку, из-за которой сессию теряли: человеку больше не надо помнить, что
окно нельзя закрывать до Enter.
"""
from app.application.login import wait_for_login


def test_an_already_open_session_is_noticed_at_once():
    slept = []
    assert wait_for_login(lambda: True, sleep=slept.append) is True
    assert slept == [], "спать незачем, мы уже внутри"


def test_it_waits_while_the_person_is_typing_their_password():
    answers = iter([False, False, True])
    slept = []
    assert wait_for_login(lambda: next(answers), sleep=slept.append) is True
    assert len(slept) == 2, "по паузе на каждую неудачную проверку"


def test_it_gives_up_instead_of_hanging_forever():
    slept = []
    assert wait_for_login(lambda: False, sleep=slept.append, attempts=4) is False
    assert len(slept) == 3, "между четырьмя проверками три паузы, не четыре"


def test_a_page_that_throws_is_just_a_not_yet():
    """Страница перезагружается под нами, пока человек ходит по форме входа."""
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise RuntimeError("Execution context was destroyed")
        return True

    assert wait_for_login(flaky, sleep=lambda s: None) is True


def test_the_interval_is_what_the_caller_asked_for():
    slept = []
    wait_for_login(lambda: False, sleep=slept.append, attempts=3, interval=1.5)
    assert slept == [1.5, 1.5]
