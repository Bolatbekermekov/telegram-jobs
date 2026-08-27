"""CV выбирается на каждый лид, значит приходит в вызов, а не в конструктор."""
from app.application.generate_message import GenerateMessage, generate_for
from app.domain.lead import Lead


class _Ai:
    def __init__(self):
        self.seen_cv = None

    def generate(self, cv_text, profile_text, vacancy_context, language=""):
        self.seen_cv = cv_text
        return "письмо"

    def generate_with_note(self, cv_text, profile_text, vacancy_context,
                           note_limit, language=""):
        self.seen_cv = cv_text
        return "письмо", "записка"


class _Chan:
    name = "linkedin"
    note_limit = 200


class _Plain:
    name = "telegram"


def _lead():
    return Lead(row=2, lead_id="1", platform="linkedin", target="u",
                vacancy_context="вакансия", raw_text="вакансия", status="new")


def test_per_call_cv_wins_over_the_constructor_one():
    ai = _Ai()
    GenerateMessage(ai, "СТАРОЕ-CV", "profile").execute(_lead(), "CV-ПОД-РОЛЬ")
    assert ai.seen_cv == "CV-ПОД-РОЛЬ"


def test_without_a_per_call_cv_the_constructor_one_is_used():
    ai = _Ai()
    GenerateMessage(ai, "СТАРОЕ-CV", "profile").execute(_lead())
    assert ai.seen_cv == "СТАРОЕ-CV"


def test_the_note_path_gets_the_same_cv():
    ai = _Ai()
    GenerateMessage(ai, "СТАРОЕ-CV", "profile").execute_with_note(
        _lead(), 200, "CV-ПОД-РОЛЬ")
    assert ai.seen_cv == "CV-ПОД-РОЛЬ"


def test_generate_for_passes_the_cv_on_the_note_channel():
    ai = _Ai()
    generate_for(GenerateMessage(ai, "СТАРОЕ-CV", "p"), _lead(), _Chan(), "CV-ПОД-РОЛЬ")
    assert ai.seen_cv == "CV-ПОД-РОЛЬ"


def test_generate_for_passes_the_cv_on_a_plain_channel():
    ai = _Ai()
    generate_for(GenerateMessage(ai, "СТАРОЕ-CV", "p"), _lead(), _Plain(), "CV-ПОД-РОЛЬ")
    assert ai.seen_cv == "CV-ПОД-РОЛЬ"
