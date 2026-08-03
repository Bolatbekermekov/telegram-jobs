"""Что модель ответила работодателю — в «Заметку», чтобы это можно было увидеть.

Вопросы в формах отклика отвечает LLM, и до сих пор её ответы нигде не
сохранялись: заявка уходила, а чем именно мы представились работодателю,
узнать было неоткуда.

Точка перехвата одна на все площадки: и внешние формы (external_apply,
LinkedIn Easy Apply, RemoteOK), и hh зовут ОДИН И ТОТ ЖЕ answerer.
"""
from app.application.answer_log import AnswerLog, answers_note, wrap_answerer

QUESTIONS = [
    {"id": "0", "type": "text", "prompt": "Years of experience", "options": []},
    {"id": "1", "type": "choice", "prompt": "Willing to relocate?",
     "options": ["Yes", "No", "Maybe"]},
]


def _answerer(_questions, _vacancy):
    return {"0": {"text": "3"}, "1": {"choice": 1}}


def test_the_wrapped_answerer_still_returns_what_the_caller_expects():
    """Обёртка не должна менять поведение: её задача — только запомнить."""
    log = AnswerLog()
    assert wrap_answerer(_answerer, log)(QUESTIONS, "вакансия") == _answerer(None, None)


def test_a_free_text_answer_is_recorded():
    log = AnswerLog()
    wrap_answerer(_answerer, log)(QUESTIONS, "вакансия")
    assert ("Years of experience", "3") in log.pairs


def test_a_choice_is_recorded_as_the_option_text_not_its_index():
    """«1» в заметке не говорит ничего. Смотреть на неё будет человек."""
    log = AnswerLog()
    wrap_answerer(_answerer, log)(QUESTIONS, "вакансия")
    assert ("Willing to relocate?", "No") in log.pairs


def test_answers_accumulate_across_several_calls():
    """LinkedIn Easy Apply спрашивает по шагам — за один отклик answerer
    вызывается несколько раз."""
    log = AnswerLog()
    wrapped = wrap_answerer(_answerer, log)
    wrapped(QUESTIONS, "в")
    wrapped([{"id": "0", "type": "text", "prompt": "Salary", "options": []}], "в")
    assert len(log.pairs) == 3


def test_reset_keeps_one_leads_answers_out_of_the_next():
    log = AnswerLog()
    wrap_answerer(_answerer, log)(QUESTIONS, "в")
    log.reset()
    assert log.pairs == []


def test_a_broken_answerer_still_reaches_the_caller():
    """Запись ответов не должна ни ломать отклик, ни прятать его ошибку."""
    def boom(_q, _v):
        raise RuntimeError("OpenAI down")

    log = AnswerLog()
    try:
        wrap_answerer(boom, log)(QUESTIONS, "в")
    except RuntimeError as exc:
        assert "OpenAI down" in str(exc)
    else:
        raise AssertionError("ошибка answerer-а должна дойти до вызывающего")


# --- как это выглядит в листе ------------------------------------------------

def test_the_note_shows_question_and_answer_together():
    got = answers_note([("Years of experience", "3"),
                        ("Willing to relocate?", "No")])
    assert "Years of experience" in got and "3" in got
    assert "Willing to relocate?" in got and "No" in got


def test_no_questions_means_no_note():
    assert answers_note([]) == ""


def test_a_very_long_answer_is_trimmed():
    """Ячейка листа не резиновая, а читать её будет человек глазами."""
    got = answers_note([("Why us?", "очень длинный ответ " * 500)])
    assert len(got) <= 3000
