"""Ссылка в ATS — это адрес отклика, а не «контакта не нашлось».

Единственный жёсткий отказ во всём интейке — `extract_lead` роняет лид, если
`detect_contact` вернул None. Именно в эту дыру и проваливались ссылки на
Greenhouse и Lever: у такой страницы контакта в человеческом смысле нет и быть
не может, отклик там идёт формой. Лид терялся целиком, бот отвечал «⚠️ Не нашёл
контакт», в таблицу не попадало ничего.

Правило стоит ПОСЛЕДНИМ, перед `return None`, и это не случайность: у hh,
LinkedIn и Wellfound есть собственные каналы отклика, а живой человек в телеграме
лучше любой формы. `ats` подбирает только то, что иначе было бы потеряно.
"""
from app.domain.contact import Contact, detect_contact
from app.domain.vacancy_text import pick_vacancy_url

JOB = "https://boards.greenhouse.io/block/jobs/5406229008"


def test_a_bare_ats_link_becomes_a_lead():
    assert detect_contact(JOB) == Contact("ats", JOB)


def test_a_live_person_still_wins_over_a_form():
    """Пост рекрутёра с ником и ссылкой: пишем человеку, а не в форму."""
    text = f"Ищем Python-разработчика, откликайтесь: {JOB}\nВопросы: @hr_anna"
    assert detect_contact(text) == Contact("telegram", "@hr_anna")


def test_but_the_vacancy_is_still_read_from_the_ats_link():
    """Контакт и источник текста — разные вопросы.

    Раньше эта пара расходилась молча: лид сохранялся как telegram, ссылка
    оставалась просто текстом, и «Вакансия» собиралась из слов пересылающего.
    """
    text = f"Ищем Python-разработчика, откликайтесь: {JOB}\nВопросы: @hr_anna"
    assert pick_vacancy_url(text) == JOB


def test_a_link_without_the_scheme_still_gets_one():
    """Без схемы это не адрес, который откроет браузер отправителя."""
    assert detect_contact("boards.greenhouse.io/block/jobs/5406229008") == \
        Contact("ats", JOB)


# --- пара правил не должна разойтись -------------------------------------

def test_everything_vacancy_text_calls_an_ats_link_also_becomes_a_lead():
    """`_ATS_RE` и `is_ats_job_url` — близнецы в разных модулях.

    Разойдясь, они дают худший из возможных исходов: ссылка считается вакансией
    и читается, но контакта под неё нет, и лид всё равно выбрасывается. Или
    наоборот — лид есть, а «Вакансия» пустая. Держим их согласованными тестом.
    """
    from tests.test_ats_job_url import VENDORS
    missed = [u for u in VENDORS if detect_contact(u) != Contact("ats", u)]
    assert missed == []


def test_and_neither_of_them_takes_a_company_landing_page():
    from tests.test_ats_job_url import ROOTS
    assert [u for u in ROOTS if detect_contact(u) is not None] == []
