"""Ответы в анкетах — подробные там, где работодатель спрашивает по существу.

Замер 2026-09-24 по 406 парам «вопрос — ответ» из заметок: у 49 открытых
вопросов (why / describe / tell us / «расскажите») медиана ответа 9 слов, и 19
из 49 получили 1-3 слова. «What is your hands-on experience with deploying AI
in production?» -> «I have directly deployed and managed AI systems in
production execution.» Текстовые вопросы да/нет на hh получали голое «Да»:
«Были сложные ситуации (факапы), которые удалось разрешить?» -> «Да».

Причина была в промпте: «Свободные текстовые ответы: коротко, по делу, честно,
1-3 предложения». Правило теперь по типу вопроса: открытый — подробно и
конкретно, да/нет в текстовом поле — ответ плюс подтверждение, короткий факт —
коротко. Ограничение самого поля важнее длины.
"""
from app.infrastructure.openai_client import _QUESTIONS_SYSTEM

LOW = _QUESTIONS_SYSTEM.lower()


def test_the_blanket_one_to_three_sentences_rule_is_gone():
    assert "1-3 предложения" not in LOW


def test_open_questions_get_a_detailed_concrete_answer():
    assert "подробно" in LOW
    assert "3-5 предложений" in LOW
    assert "не длиннее 500 знаков" in LOW
    # Конкретика, а не общие слова: проект, технологии, что делал, результат.
    for word in ("проект", "технолог", "результат"):
        assert word in LOW


def test_a_yes_no_question_in_a_text_field_is_never_one_word():
    assert "никогда не отвечай одним словом" in LOW


def test_missing_direct_experience_is_said_honestly_with_the_closest_real_one():
    assert "самый близкий реальный опыт" in LOW


def test_short_facts_stay_short():
    assert "короткий факт" in LOW


def test_the_fields_own_limit_beats_the_length():
    assert "важнее этой длины" in LOW


def test_no_invented_past_events():
    """Вопрос «расскажите о случае», а случая в CV нет — не выдумывать событие."""
    assert "не выдумывая событие" in LOW


def test_yes_only_for_direct_experience():
    """Живьём 2026-09-25: «Do you have experience with subscription products?» ->
    «Yes», а подтверждение — про авторизацию и аккаунты. Смежный опыт — это «No»
    плюс честно названный смежный, а не «Yes»."""
    assert "только если в cv есть прямой опыт" in LOW


def test_numbers_are_written_as_digits():
    """Там же: «four hundred twenty milliseconds», «forty to sixty percent»."""
    assert "числа пиши цифрами" in LOW


def test_a_summary_field_is_a_profile_not_a_letter():
    """Поле «Summary» получило «Hi. I am applying for the Software Engineer role…»."""
    assert "без приветствия" in LOW


def test_the_yes_rule_carries_a_worked_example():
    """Одного правила модели не хватило: после него «subscription products» всё
    равно получали «Yes» со смежным опытом (живьём 2026-09-25, 2 из 2). Пример в
    промпте держит её надёжнее общих слов."""
    assert "subscription products" in LOW
    assert "no, i haven't" in LOW
