"""Ответы на анкету работодателя идут на языке вакансии, а не всегда по-русски.

В `_QUESTIONS_SYSTEM` язык стоял константой: «коротко, по делу, честно, на
русском». Правило `language_rule` в этот промпт не добавлялось никогда, хотя
письму его называют прямо с тех пор, как выяснилось, что строка «язык сообщения
= язык вакансии» проигрывает русскому языку самого промпта.

Из-за этого английская вакансия получала английское письмо и русские ответы в
форме работодателя — в одном отклике.

Русский при этом остаётся ПРАВИЛЬНЫМ ответом там, где вакансия русская: у hh.ru
все объявления по-русски, и анкета на них тоже.
"""
from app.infrastructure.openai_client import OpenAIMessageGenerator

RU_VACANCY = ("Инженер по тестированию (Python). Формат работы: тестирование "
              "desktop-приложения на Linux, разработка автотестов на Pytest.")
EN_VACANCY = ("Senior Backend Engineer. You will own our scheduling service. "
              "Requirements: 3+ years with Go, strong SQL, Docker and CI.")
QUESTIONS = [{"id": "1", "type": "text", "prompt": "Почему вам интересна вакансия?"}]


class _FakeCompletions:
    def __init__(self, content):
        self.calls = []
        self._content = content

    def create(self, **kw):
        self.calls.append(kw)

        class _Msg:
            content = self._content

        class _Choice:
            message = _Msg()

        class _Resp:
            choices = [_Choice()]

        return _Resp()


class _FakeClient:
    def __init__(self, content):
        self.chat = type("_Chat", (), {"completions": _FakeCompletions(content)})()


def _generator(content='{"answers":[{"id":"1","text":"ok"}]}'):
    gen = OpenAIMessageGenerator.__new__(OpenAIMessageGenerator)
    gen._client = _FakeClient(content)
    gen._model = "writing-model"
    gen._max_output_tokens = 2000
    return gen


def _system_for(vacancy_context, **kw):
    gen = _generator()
    gen.answer_questions(cv_text="cv", profile_text="p",
                         vacancy_context=vacancy_context, questions=QUESTIONS, **kw)
    (call,) = gen._client.chat.completions.calls
    return call["messages"][0]["content"]


def test_an_english_vacancy_gets_an_english_rule():
    system = _system_for(EN_VACANCY)
    assert "English" in system
    assert "ПО-АНГЛИЙСКИ" in system


def test_a_russian_vacancy_still_gets_russian():
    """У hh.ru вакансии русские — и русский ответ там правильный."""
    system = _system_for(RU_VACANCY)
    assert "по-русски" in system
    assert "English" not in system


def test_an_empty_vacancy_stays_russian():
    """Пустое описание это отсутствие сигнала, а не английская вакансия."""
    assert "по-русски" in _system_for("")


def test_the_caller_can_name_the_language_outright():
    """Как у письма: язык можно передать аргументом, а не пересчитывать по тексту."""
    system = _system_for(RU_VACANCY, language="en")
    assert "English" in system


def test_the_language_is_no_longer_nailed_to_russian_in_the_prompt():
    """Раньше «на русском» стояло в самом _QUESTIONS_SYSTEM и не отключалось."""
    from app.infrastructure.openai_client import _QUESTIONS_SYSTEM

    assert "на русском" not in _QUESTIONS_SYSTEM


def test_the_question_own_language_requirement_still_wins():
    """В вопросах работодателя часто пишут «(на английском)».

    Правило языка дописывается в КОНЕЦ промпта и потому читается последним —
    без оговорки оно перебило бы условие самого вопроса, а в промпте прямо
    сказано, что ответ, нарушающий условие вопроса, хуже пустого.
    """
    system = _system_for(RU_VACANCY)
    tail = system[system.index("ВАЖНО: вакансия"):]
    assert "вопрос" in tail.lower()


def test_the_answers_are_named_so_the_rule_has_something_to_apply_to():
    """`language_rule` говорит «сообщение», а здесь сообщения нет — есть ответы."""
    system = _system_for(EN_VACANCY)
    assert "ответ" in system[system.index("IMPORTANT:"):].lower()
