"""Ответы на вопросы анкет пишутся по резюме той роли, под которую идёт отклик.

Живьём 2026-09-14 (проверка «везде ли PDF под роль»): письмо и вложение уходили
под роль, а модель, отвечающая на вопросы анкет — hh, LinkedIn Easy Apply,
внешние формы, — всегда читала запасное резюме из CV_PATH, то есть Fullstack.
На AI-вакансию «опыт с RAG» описывался по резюме фулстека.

Контракт `answerer(questions, vacancy_context)` не меняется: у настоящего
answerer-а есть `for_cv(path)`, и каналы берут его через `answerer_for_cv`.
Заглушки без `for_cv` работают как раньше.
"""
from types import SimpleNamespace

from app.application.answer_log import AnswerLog, wrap_answerer
from app.application.answerer_cv import answerer_for_cv
from app.domain.channel import OutreachContent

AI_CV = "/cv/ai/Bolatbek_Yermekov_AI_Engineer.pdf"
QUESTIONS = [{"id": "0", "type": "text", "prompt": "Describe your RAG experience", "options": []}]


def _base_and_role():
    """Answerer, который по привязке к AI-резюме отвечает иначе, чем без неё."""
    def role(questions, vacancy_context):
        return {q["id"]: {"text": "по резюме AI"} for q in questions}

    def base(questions, vacancy_context):
        return {q["id"]: {"text": "по резюме Fullstack"} for q in questions}

    base.for_cv = lambda path: role if path == AI_CV else base
    return base, role


def test_the_real_answerer_reads_the_resume_of_the_role(monkeypatch):
    from app.infrastructure import cv_loader, openai_client
    from app.infrastructure.channels import registry

    monkeypatch.setattr(cv_loader, "load_cv_text", lambda path: f"CV from {path}")
    monkeypatch.setattr(cv_loader, "load_text_file", lambda path: "profile")
    seen = []
    monkeypatch.setattr(openai_client.OpenAIMessageGenerator, "answer_questions",
                        lambda self, cv_text, profile_text, vacancy_context, questions,
                        language="": seen.append(cv_text) or {})
    config = SimpleNamespace(LLM_API_KEY="k", LLM_MODEL="m", OPENAI_MAX_OUTPUT_TOKENS=100,
                             LLM_BASE_URL=None, CV_PATH="/cv/fullstack/Fullstack.pdf",
                             PROFILE_PATH="/profile.md",
                             APPLY_PROFILE_PATH="/nonexistent/apply_profile.yml", CONTACTS=None)
    answerer = registry._hh_answerer(config)

    answerer(QUESTIONS, "vacancy")
    answerer_for_cv(answerer, AI_CV)(QUESTIONS, "vacancy")

    assert seen == ["CV from /cv/fullstack/Fullstack.pdf", f"CV from {AI_CV}"]


def test_a_stand_in_answerer_without_a_resume_binding_is_left_as_is():
    def answerer(questions, vacancy_context):
        return {}

    assert answerer_for_cv(answerer, AI_CV) is answerer
    assert answerer_for_cv(None, AI_CV) is None


def test_the_answer_log_keeps_the_resume_binding():
    base, _ = _base_and_role()
    log = AnswerLog()

    answers = answerer_for_cv(wrap_answerer(base, log), AI_CV)(QUESTIONS, "ctx")

    assert answers == {"0": {"text": "по резюме AI"}}
    assert log.pairs == [("Describe your RAG experience", "по резюме AI")]


def test_an_external_form_is_answered_by_the_resume_it_uploads():
    from app.domain.apply_profile import ApplyProfile
    from app.domain.page_observation import FieldObs, PageObservation
    from app.infrastructure.channels import external_apply as ea
    from tests.test_external_apply import FakePage

    base, _ = _base_and_role()
    page = FakePage(PageObservation(url="https://careers.factorialhr.com/apply/x", file_inputs=1, fields=[
        FieldObs(tag="input", type="email", label="Email", required=True, ref="0"),
        FieldObs(tag="textarea", type="", label="Why do you want this role? *", required=True, ref="1"),
    ]), present=[ea.SEL_SUBMIT])

    ea.external_apply(page, "https://careers.factorialhr.com/apply/x", OutreachContent(body="hi"),
                      ApplyProfile(full_name="B Y", email="a@b.com"), AI_CV, answerer=base)

    assert page.filled['[data-af="1"]'] == "по резюме AI"


def test_easy_apply_is_answered_by_the_resume_it_attaches(monkeypatch):
    from app.application import auto_apply
    from app.application.auto_apply import ApplyPlan
    from app.domain.page_observation import FieldObs, PageObservation
    from app.infrastructure.channels import external_apply, linkedin
    from tests.test_linkedin_channel import _FakeApplyPage

    base, role = _base_and_role()
    used = []
    monkeypatch.setattr(linkedin, "_choose_resume", lambda page, cv_path, job_url, **kw: None)
    monkeypatch.setattr(linkedin, "_resume_card_group_names", lambda page: set())
    step = PageObservation(fields=[FieldObs(tag="input", type="text", label="City", ref="0")])
    monkeypatch.setattr(external_apply, "scrape_until_ready", lambda page: (step, None))
    monkeypatch.setattr(external_apply, "fill_fields", lambda page, plan, where="": None)
    monkeypatch.setattr(auto_apply, "build_plan",
                        lambda obs, profile, cv_path, cover_letter_path="": ApplyPlan(actions=[]))
    monkeypatch.setattr(auto_apply, "answer_ai_fields",
                        lambda plan, answerer, vacancy_context: used.append(answerer))
    page = _FakeApplyPage({linkedin.SEL_EASY_APPLY: 1, linkedin.SEL_APPLY_SUBMIT: [0, 1],
                           linkedin.SEL_APPLY_NEXT: 1},
                          href="https://www.linkedin.com/jobs/view/2/apply/")

    linkedin.easy_apply_via_page(page, "https://www.linkedin.com/jobs/view/2",
                                 OutreachContent(body="hi"), profile=object(),
                                 cv_path=AI_CV, answerer=base)

    assert used == [role]


def test_hh_questions_are_answered_by_the_resume_sent_to_the_chat(monkeypatch):
    import app.infrastructure.channels.headhunter as hh
    from tests.test_headhunter_channel import _FakePage

    questions = [{"id": "task_1", "type": "text", "prompt": "p", "options": []}]
    monkeypatch.setattr(hh, "collect_questions", lambda page: questions)
    monkeypatch.setattr(hh, "_verify_submitted", lambda page, debug_dir=None: None)
    page = _FakePage({hh.SEL_APPLY: 1, hh.SEL_LETTER_TOGGLE: 1, hh.SEL_QUESTIONS: 1,
                      hh.SEL_LETTER_INPUT: 1, hh.SEL_SUBMIT: 1})
    base, _ = _base_and_role()

    hh.apply_via_page(page, "https://hh.ru/vacancy/1",
                      OutreachContent(body="letter", attachment_path=AI_CV), base)

    assert ("fill", "textarea[name='task_1_text']", "по резюме AI") in page.actions
