"""Наша собственная разметка — не описание вакансии, и письма из неё не пишут.

Лид #930 (замер 2026-09-07) ушёл живому рекрутёру LinkedIn, имея в «Вакансии»
ровно одну строку — нашу же оценку:

    86/100: Frontend Engineer; React/React Native совпадает, уровень для
    junior/middle, стек релевантен

`needs_vacancy_refetch` вернула False (текст не пуст и не отказ модели), ссылку
никто не перечитал, и письмо писалось из этой строки и резюме. На момент замера
таких лидов в очереди было 18 из 73, а отправленных за всё время — 21.

Ту же мысль про «наша разметка не считается» уже несёт message_language:
_SCORE_NOTE и _OWN_LABEL_LINE там выброшены из подсчёта языка. Здесь она нужна
второй раз — для решения «перечитать или нет».
"""
from app.application.send_plan import needs_vacancy_refetch

LEAD_930 = ("86/100: Frontend Engineer; React/React Native совпадает, "
            "уровень для junior/middle, стек релевантен")
LEAD_929 = ("AI Engineer — SoftServe\n"
            "Локация: Саудовская Аравия (Удаленная работа)\n"
            "88/100: AI Engineer совпадает; уровень Intern/Junior/Middle подходит")


def test_only_our_score_needs_a_refetch():
    assert needs_vacancy_refetch(LEAD_930) is True


def test_only_our_labels_need_a_refetch():
    assert needs_vacancy_refetch("Локация: Москва\nЗарплата: 300000") is True


def test_score_plus_labels_and_nothing_else_needs_a_refetch():
    assert needs_vacancy_refetch("Компания: Acme\n70/100: подходит по стеку") is True


def test_a_real_title_survives_and_is_not_refetched():
    # У #929 кроме разметки есть роль и компания — это уже описание, пусть и
    # тонкое. Перечитывать всё подряд значит платить запросом за каждый лид.
    assert needs_vacancy_refetch(LEAD_929) is False


def test_a_normal_description_is_not_refetched():
    assert needs_vacancy_refetch(
        "Ищем Python-разработчика. Django, PostgreSQL, удалённо.") is False


def test_the_old_cases_still_hold():
    assert needs_vacancy_refetch("") is True
    assert needs_vacancy_refetch("   ") is True
