"""Сокращение записки без порчи смысла.

Все письма в LinkedIn уходили обрезанными на полумысли — «…amoCRM, Google Sheets
и», «…нужно доводить», «…Это» — потому что канал нёс один предел (300, размер
записки к приглашению), а общий `_truncate` режет по ближайшему пробелу. Там, где
сокращать действительно надо, сокращаем по границе предложения.
"""
from app.infrastructure.channels.linkedin import _trim_to_sentence


def test_text_within_the_limit_is_untouched():
    assert _trim_to_sentence("Здравствуйте. Коротко.", 100) == "Здравствуйте. Коротко."


def test_shortens_to_the_last_whole_sentence():
    text = "Здравствуйте. Откликаюсь на вакансию Backend. Готов обсудить детали."
    out = _trim_to_sentence(text, 50)
    assert out == "Здравствуйте. Откликаюсь на вакансию Backend."
    assert len(out) <= 50


def test_question_and_exclamation_end_a_sentence():
    text = "Здравствуйте! Есть вопрос по вакансии? И ещё текст."
    assert _trim_to_sentence(text, 40) == "Здравствуйте! Есть вопрос по вакансии?"


def test_a_dot_inside_a_word_is_not_a_sentence_end():
    """«Atlanti.ai» — название продукта, а не конец мысли."""
    text = "Работаю в Atlanti.ai и строю интеграции. Дальше не влезет."
    assert _trim_to_sentence(text, 45) == "Работаю в Atlanti.ai и строю интеграции."


def test_falls_back_to_a_word_boundary_when_no_sentence_fits():
    """Обрезанное первое предложение лучше пустой записки: слать больше нечего."""
    assert _trim_to_sentence("Очень длинное первое предложение без конца", 20) == "Очень длинное"


def test_empty_and_none_are_safe():
    assert _trim_to_sentence("", 10) == ""
    assert _trim_to_sentence(None, 10) == ""


def test_a_dot_landing_exactly_on_the_cut_boundary_is_not_a_sentence_end():
    """Точка на последнем символе окна обрезки — всё ещё середина домена, а не
    конец мысли. Регулярка по окну этого не видит: `$` совпадает с концом окна."""
    text = "Смотри Atlanti.ai и потом ещё много текста"
    assert _trim_to_sentence(text, 15) == "Смотри"
