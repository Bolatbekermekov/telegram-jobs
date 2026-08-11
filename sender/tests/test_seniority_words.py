"""Уровень не должен звучать ни в письме, ни в записке.

Запрет в промпте («не называй уровень кандидата») закрывал только половину:
модель перестала писать «как senior-разработчик», но продолжила переносить в
письмо заголовок вакансии целиком — «откликаюсь на вакансию Senior Go
Developer». Читателю всё равно, откуда слово взялось: уровень в письме стоит.

Промпт это просьба, поэтому рядом с ним стоит сетка после генерации, ровно как
у запрета тире. Тесты держат обе: и правило в `_SYSTEM`, и вырезание в тексте,
который реально уходит из `OpenAIMessageGenerator`.
"""
from app.domain.seniority import strip_seniority
from app.infrastructure.openai_client import _SYSTEM, OpenAIMessageGenerator


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


def _generator(content):
    gen = OpenAIMessageGenerator.__new__(OpenAIMessageGenerator)
    gen._client = _FakeClient(content)
    gen._model = "writing-model"
    gen._max_output_tokens = 2000
    return gen


# --- вырезание --------------------------------------------------------------

def test_the_vacancy_title_loses_its_level_and_keeps_the_role():
    """Живой случай: «Senior Go Developer» надо назвать «Go Developer», а не
    «разработчиком» — роль из заголовка остаётся, уходит только грейд."""
    assert strip_seniority("Откликаюсь на вакансию Senior Go Developer.") == (
        "Откликаюсь на вакансию Go Developer.")


def test_a_level_at_the_start_of_a_line_leaves_no_leading_space():
    assert strip_seniority("Middle QA Engineer это про меня.") == (
        "QA Engineer это про меня.")


def test_a_plus_does_not_survive_its_word():
    assert strip_seniority("Ищете Middle+ Python разработчика.") == (
        "Ищете Python разработчика.")


def test_a_pair_of_levels_goes_together():
    assert strip_seniority("Вакансия Middle/Senior Frontend Developer.") == (
        "Вакансия Frontend Developer.")


def test_a_hyphenated_level_goes_whole():
    assert strip_seniority("This is a mid-level backend role.") == (
        "This is a backend role.")


def test_a_grade_phrase_does_not_leave_a_broken_sentence():
    """«уровню» без слова после него — обрубок, который прочитает человек."""
    assert strip_seniority("Мой опыт соответствует уровню Senior.") == (
        "Мой опыт соответствует.")


def test_a_grade_glued_to_its_word_takes_the_word_with_it():
    """Иначе остаётся «расти до -уровня» — заметнее, чем сам грейд."""
    assert strip_seniority("Готов расти до senior-уровня.") == "Готов расти."
    assert strip_seniority("Закрываю задачи middle-грейда.") == "Закрываю задачи."


def test_a_dangling_kak_goes_with_the_grade_at_the_end_of_a_clause():
    assert strip_seniority("Опыт 5 лет, из них 3 как Senior.") == (
        "Опыт 5 лет, из них 3.")


def test_but_kak_survives_when_a_role_follows_it():
    """«как Senior Go Developer» — уходит одно слово, оборот остаётся целым."""
    assert strip_seniority("Работаю как Senior Go Developer в Acme.") == (
        "Работаю как Go Developer в Acme.")


def test_russian_spellings_are_covered_too():
    assert "сеньор" not in strip_seniority("Работаю как сеньор в команде.").lower()
    assert "миддл" not in strip_seniority("Позиция миддл разработчика.").lower()


def test_brackets_that_held_only_the_level_go_with_it():
    assert strip_seniority("Роль (Senior) в продуктовой команде.") == (
        "Роль в продуктовой команде.")


def test_a_longer_word_that_merely_starts_with_a_level_survives():
    """`senior` внутри `seniority` — не грейд, и резать его нельзя."""
    kept = strip_seniority("The seniority of the team matters, джуниоров нет.")
    assert kept == "The seniority of the team matters, джуниоров нет."


def test_paragraph_breaks_survive_the_cleanup():
    """Письмо это несколько коротких абзацев; схлопнуть их в стену текста
    нельзя, поэтому уборка трогает только пробелы и табы."""
    got = strip_seniority("Senior Go Developer, добрый день.\n\nМой стек: Go, gRPC.")
    assert got == "Go Developer, добрый день.\n\nМой стек: Go, gRPC."


def test_an_empty_text_stays_empty():
    assert strip_seniority("") == ""


def test_a_text_without_levels_is_returned_untouched():
    text = "Здравствуйте. Сейчас работаю в Acme над платежами.\n\nМой стек: Go, Kafka."
    assert strip_seniority(text) == text


# --- промпт -----------------------------------------------------------------

def test_the_prompt_forbids_the_words_for_the_vacancy_too():
    """Старая формулировка запрещала уровень «кандидата», и заголовок вакансии
    проходил мимо неё."""
    low = _SYSTEM.lower()
    assert "не пиши слова уровня" in low
    assert "ни про вакансию" in low


# --- то, что реально уходит из генератора ------------------------------------

def test_the_letter_leaves_the_generator_clean():
    gen = _generator("Откликаюсь на вакансию Senior Go Developer.")
    assert gen.generate("cv", "profile", "Senior Go Developer") == (
        "Откликаюсь на вакансию Go Developer.")


def test_the_linkedin_note_is_cleaned_as_well_as_the_letter():
    """Записка это отдельный текст к запросу на контакт, и её тоже читает
    человек — сетка над письмом её не покрывает."""
    gen = _generator('{"letter": "Пишу по вакансии Senior Go Developer.",'
                     ' "note": "Здравствуйте! Middle+ Go Developer это про меня."}')
    letter, note = gen.generate_with_note("cv", "profile", "Senior Go Developer", 200)
    assert letter == "Пишу по вакансии Go Developer."
    assert note == "Здравствуйте! Go Developer это про меня."
