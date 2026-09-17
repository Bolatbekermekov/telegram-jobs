"""Работодатель прямо просит отвечать без ИИ — такой отклик мы не пишем моделью.

Живьём 2026-09-17 (лид #1411, jobs.ashbyhq.com/makai-labs): над обязательной
галочкой стоит просьба отвечать на вопросы анкеты без ИИ, а любой ИИ-ответ
объявлен поводом снять кандидата с рассмотрения. Наш бот пишет ответы моделью —
значит, туда он не пишет вовсе, а лид уходит в ручные с этой причиной.

Весь текст ниже снят с той самой страницы (`document.body.innerText`), включая
отрицательные примеры: вакансия сама про ИИ, и правило не должно срабатывать ни
на её названии, ни на вопросах про опыт с LLM — половина нашего потока такая.
"""
from app.domain.ai_answer_ban import ai_answers_forbidden

# Подпись обязательной галочки, снятая с формы #1411 (Makai Labs, Ashby).
BAN = (
    "Important Reminder: To help us better understand your communication style "
    "and thought process, we ask that you answer the screening questions without "
    "the use of AI writing tools (e.g., ChatGPT). We’re looking to evaluate "
    "your natural writing ability, and any use of AI assistance may lead to "
    "disqualification."
)

# Вопросы той же формы — про ИИ, но ничего не запрещают.
AI_VACANCY = (
    "AI Engineer\n"
    "AI/LLM Experience - Describe your hands-on experience building or deploying "
    "AI/LLM-powered systems in production environments.\n"
    "AI Frameworks / Tooling - Which AI/ML tools or frameworks have you worked with?\n"
)


def test_the_ashby_reminder_is_recognised_as_a_ban():
    assert ai_answers_forbidden(BAN)


def test_the_whole_page_text_of_1411_trips_the_rule():
    assert ai_answers_forbidden(AI_VACANCY + "\n" + BAN)


def test_the_quoted_reason_names_the_ban_itself():
    """Причина попадёт в таблицу человеку — в ней должна быть сама просьба."""
    said = ai_answers_forbidden(BAN)
    assert "AI writing tools" in said or "ChatGPT" in said
    assert len(said) <= 200, "цитата в заметке должна быть короткой"


def test_an_ai_vacancy_is_not_a_ban():
    assert not ai_answers_forbidden(AI_VACANCY)


def test_a_company_that_merely_says_it_avoids_llms_is_not_a_ban():
    """«Мы не используем LLM» — рассказ о себе, а не условие для кандидата."""
    assert not ai_answers_forbidden(
        "We don't use LLMs for ranking; our search is built on classic IR.")


def test_a_russian_ban_is_recognised():
    assert ai_answers_forbidden(
        "Просим вас отвечать на вопросы анкеты без использования ChatGPT "
        "и других нейросетей.")
