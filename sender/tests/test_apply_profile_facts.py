"""Анкетные факты кандидата доходят до модели, которая отвечает на вопросы формы.

Живьём 2026-09-13, Workable (лид #1164): обязательное поле одним вопросом
спрашивает «1) LinkedIn URL 2) Current Location 3) Expected salary in USD per
year 4) Preference for remote/hybrid/on-site 5) work authorisation 6) when you are
available to start». Правила форм берут ответы из apply_profile.yml, но только
для коротких подписей, а модель видела лишь резюме и profile.md: ни ссылки на
LinkedIn, ни срока выхода, ни разрешения на работу там нет. По правилу честности
(факт о кандидате, которого нет в CV/PROFILE, — пустой ответ) поле осталось
пустым, и заявка ушла в ручной отклик.
"""
from types import SimpleNamespace

from app.domain.apply_profile import ApplyProfile, apply_profile_facts


def _profile():
    return ApplyProfile(
        full_name="Bolatbek Yermekov", email="me@example.com", phone="+7 775 720 0604",
        city="Astana", country="Kazakhstan",
        linkedin="https://www.linkedin.com/in/bolatbek", github="https://github.com/bolatbek",
        work_authorization="Citizen of Kazakhstan", needs_visa_sponsorship=False,
        open_to_relocation=True, notice_period="1 month",
    )


def test_the_facts_name_what_forms_ask():
    facts = apply_profile_facts(_profile())
    for fact in ("https://www.linkedin.com/in/bolatbek", "https://github.com/bolatbek",
                 "Astana, Kazakhstan", "Citizen of Kazakhstan", "1 month"):
        assert fact in facts


def test_email_and_phone_stay_out():
    """У формы для них свои поля, а в свободном ответе их остановит защита."""
    facts = apply_profile_facts(_profile())
    assert "me@example.com" not in facts
    assert "775" not in facts


def test_a_blank_profile_asserts_nothing():
    """Пустой профиль — не «визы не нужно, переезд нет», а отсутствие фактов."""
    assert apply_profile_facts(ApplyProfile()) == ""


def test_the_form_answerer_sees_the_facts(monkeypatch):
    import app.infrastructure.apply_profile_loader as loader
    import app.infrastructure.cv_loader as cv_loader
    import app.infrastructure.openai_client as openai_client
    from app.infrastructure.channels import registry

    seen = {}

    class FakeAI:
        def __init__(self, *a, **kw):
            pass

        def answer_questions(self, cv_text, profile_text, vacancy_context, questions):
            seen["profile"] = profile_text
            return {}

    monkeypatch.setattr(openai_client, "OpenAIMessageGenerator", FakeAI)
    monkeypatch.setattr(cv_loader, "load_cv_text", lambda path: "CV")
    monkeypatch.setattr(cv_loader, "load_text_file", lambda path: "PROFILE.MD")
    monkeypatch.setattr(loader, "load_apply_profile", lambda path, contacts=None: _profile())
    config = SimpleNamespace(
        LLM_API_KEY="k", LLM_MODEL="m", OPENAI_MAX_OUTPUT_TOKENS=100, LLM_BASE_URL=None,
        CV_PATH="cv.pdf", PROFILE_PATH="profile.md", APPLY_PROFILE_PATH="apply_profile.yml",
        CONTACTS=None)

    registry._hh_answerer(config)([{"id": "0", "type": "text", "prompt": "1) LinkedIn URL"}], "vacancy")

    assert seen["profile"].startswith("PROFILE.MD")
    assert "https://www.linkedin.com/in/bolatbek" in seen["profile"]
