"""Ушедшее сообщение, у которого не очистилось поле ввода, — это отправка.

Живьём 2026-09-26, лид #1698 (профиль 3-го круга, Дубай): лид лёг в `failed`
с «текст остался в поле ввода», а в переписке — наше письмо «TODAY 12:35» с
приложенным резюме Node.js. Отправка была, её не увидела проверка: единственным
признаком считалось опустевшее поле. Повтор такого лида послал бы человеку
второе письмо.

Второй признак: текст письма виден в окне переписки ЕЩЁ РАЗ, помимо поля ввода,
— значит он попал в ленту. Только в поле — значит не ушёл.
"""
import pytest

from app.domain.channel import ChannelError
from app.infrastructure.channels import linkedin as li

BODY = ("Dear HR Team,\n\nI am writing to apply for the Node.js Developer position "
        "at your company in Dubai. Currently, I work at Atlanti.ai.")


class _Composer:
    def __init__(self, text):
        self.text = text

    def inner_text(self, timeout=None):
        return self.text


class _Send:
    def count(self):
        return 1

    @property
    def last(self):
        return self

    def is_enabled(self):
        return True

    def evaluate(self, expr, timeout=None):
        pass


class _Scope:
    def __init__(self, text):
        self.text = text

    def locator(self, sel):
        return _Send()

    def inner_text(self, timeout=None):
        return self.text


class _Page:
    def wait_for_timeout(self, ms):
        pass


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    monkeypatch.setattr(li, "_SEND_CONFIRM_TIMEOUT_MS", 0)
    monkeypatch.setattr(li, "_dump_unsent_message", lambda page: None)


def test_the_letter_in_the_thread_counts_as_sent_even_if_the_box_kept_it():
    composer = _Composer(BODY)
    thread = "Bolatbek Yermekov 12:35 PM\n" + BODY + "\nBolatbek_Yermekov_Backend_NodeJS.pdf\n" + BODY
    li._press_send(_Page(), composer, _Scope(thread), body=BODY)   # не бросает


def test_the_letter_only_in_the_box_is_not_sent():
    composer = _Composer(BODY)
    with pytest.raises(ChannelError, match="текст остался в поле ввода"):
        li._press_send(_Page(), composer, _Scope("Rachel N.\n" + BODY), body=BODY)
