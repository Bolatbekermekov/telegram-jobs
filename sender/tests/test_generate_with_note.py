"""Два текста на лид, и кто из каналов их вообще просит.

Подпись приклеивается только к письму: в записку на 200 символов она не влезает,
да и LinkedIn рядом с приглашением показывает имя отправителя сам. Канал, который
не объявил `note_limit`, продолжает ходить прежним однотекстовым путём — так
правка ради LinkedIn физически не достаёт до Telegram, hh, Threads и email.
"""
from app.application.generate_message import (
    GenerateMessage, generate_for,
)
from app.domain.lead import STATUS_NEW, Lead


def _lead():
    return Lead(row=2, lead_id="1", platform="linkedin", target="t",
                vacancy_context="Backend Engineer", raw_text="", status=STATUS_NEW)


class _Ai:
    def __init__(self, letter="Письмо.", note="Записка."):
        self.note_limits = []
        self._letter, self._note = letter, note

    def generate(self, cv_text, profile_text, vacancy_context):
        return self._letter

    def generate_with_note(self, cv_text, profile_text, vacancy_context, note_limit):
        self.note_limits.append(note_limit)
        return self._letter, self._note


class _Boom:
    def generate_with_note(self, **kw):
        raise RuntimeError("openai down")

    def generate(self, **kw):
        raise RuntimeError("openai down")


class _Chan:
    def __init__(self, note_limit=None):
        if note_limit is not None:
            self.note_limit = note_limit


def test_the_signature_rides_the_letter_only():
    g = GenerateMessage(_Ai(), "cv", "profile", signature_text="Болатбек, +7 777")
    letter, note = g.execute_with_note(_lead(), 200)
    assert letter == "Письмо.\n\nБолатбек, +7 777"
    assert note == "Записка."


def test_the_channel_limit_reaches_the_model():
    ai = _Ai()
    GenerateMessage(ai, "cv", "profile").execute_with_note(_lead(), 200)
    assert ai.note_limits == [200]


def test_a_channel_with_a_note_limit_gets_both_texts():
    body, note, err = generate_for(GenerateMessage(_Ai(), "cv", "p"), _lead(),
                                   _Chan(note_limit=200))
    assert (body, note, err) == ("Письмо.", "Записка.", None)


def test_a_channel_without_a_note_limit_keeps_the_single_text_path():
    body, note, err = generate_for(GenerateMessage(_Ai(), "cv", "p"), _lead(), _Chan())
    assert body == "Письмо."
    assert note == ""
    assert err is None


def test_a_generation_failure_is_returned_not_raised():
    """Ровно тот контракт, что и у generate_body: обвал OpenAI не должен убивать
    прогон, лид остаётся `new` и повторится."""
    body, note, err = generate_for(GenerateMessage(_Boom(), "cv", "p"), _lead(),
                                   _Chan(note_limit=200))
    assert body is None
    assert note == ""
    assert isinstance(err, RuntimeError)
