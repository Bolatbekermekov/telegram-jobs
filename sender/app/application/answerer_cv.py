"""Ответы на вопросы анкеты — по резюме той роли, под которую идёт отклик."""


def answerer_for_cv(answerer, cv_path):
    """Тот же answerer, но отвечающий по резюме `cv_path`, если он так умеет.

    Живьём 2026-09-14: письмо и PDF уходили под роль, а модель отвечала на
    вопросы анкет (hh, LinkedIn Easy Apply, внешние формы) по запасному CV_PATH —
    Fullstack-резюме, и на AI-вакансию «опыт с RAG» описывался по резюме
    фулстека. Контракт `answerer(questions, vacancy_context)` не меняется:
    привязку даёт `for_cv(path)` настоящего answerer-а, заглушкам без него
    ничего не нужно.
    """
    bind = getattr(answerer, "for_cv", None)
    if answerer is None or not cv_path or bind is None:
        return answerer
    return bind(cv_path)
