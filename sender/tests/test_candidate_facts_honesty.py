"""Факты о себе агент берёт из CV и профиля, а не из требований вакансии.

Живьём 2026-09-13, лид #1001 (Easy Apply, стажёр в Мумбаи): на вопрос «Are you
completing Bachelor's in Computer Engineering or related field in 2025/2026?»
агент ответил «Yes». По CV бакалавриат (Cybersecurity, Astana IT University)
окончен в июне 2024 — ответ был бы ложью от имени кандидата. Там же поле «средний
балл от 10-го класса выше 80%?» принимает только число, а такого факта нет ни в
CV, ни в профиле: придуманная цифра — такая же ложь.
"""
from app.infrastructure.openai_client import _QUESTIONS_SYSTEM


def test_facts_about_the_candidate_come_only_from_cv_and_profile():
    low = _QUESTIONS_SYSTEM.lower()
    assert "учёб" in low or "учеб" in low
    assert "не подгоняй" in low


def test_an_unknown_personal_number_is_left_empty_not_invented():
    """Слово «пустого» в промпте уже было — про ответ, нарушающий условие. Проверяется
    именно указание вернуть пустой ответ, а не случайное совпадение слова."""
    assert "верни пустой" in _QUESTIONS_SYSTEM.lower()


def test_years_of_experience_without_an_exact_figure_are_three_to_five():
    """Решение владельца (повторено 2026-09-13, лид #1044): на неясный вопрос о
    годах опыта — общего или с конкретной технологией — число от 3 до 5. Без этой
    оговорки правило выше («факта нет, а поле ждёт число — верни пустой») оставило
    бы пустым «How many years with Kubernetes?», и обязательное поле увело бы
    отклик в ручной."""
    low = _QUESTIONS_SYSTEM.lower()
    assert "от 3 до 5" in low
    assert "годы опыта" in low
