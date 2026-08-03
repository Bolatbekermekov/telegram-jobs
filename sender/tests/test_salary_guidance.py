"""Чем модель руководствуется, называя зарплату.

Вопрос «salary expectations» встречается и в формах ATS, и в LinkedIn Easy
Apply, и он часто обязательный. Отвечала на него модель и раньше, но
единственным указанием было «разумное число для этой роли и рынка вакансии» —
без уровня, без привязки к стране и без запрета завышать. Названная наугад
цифра стоит дорого: завышенная снимает кандидата с рассмотрения молча.
"""
from app.infrastructure.openai_client import _QUESTIONS_SYSTEM


def test_the_level_is_named_so_the_figure_is_not_guessed_from_the_title():
    """Вакансия может называться «Senior», а оценивать себя надо как middle."""
    assert "middle" in _QUESTIONS_SYSTEM.lower()


def test_the_market_is_the_country_of_the_vacancy():
    low = _QUESTIONS_SYSTEM.lower()
    assert "стран" in low
    assert "европ" in low


def test_inflating_is_forbidden_explicitly():
    low = _QUESTIONS_SYSTEM.lower()
    assert "не завыша" in low or "не завыш" in low


def test_the_currency_of_the_market_is_requested():
    """Ответ «300000» без валюты в польской вакансии читается как злая шутка."""
    assert "валют" in _QUESTIONS_SYSTEM.lower()
