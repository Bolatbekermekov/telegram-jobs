"""Recognising a vacancy column that must be read again before anything is sent.

The positive cases are the two rows this was written for, copied verbatim out of
the live sheet (ids 121 and 141) — not paraphrases. The negatives are equally
real: two vacancy summaries from the same sheet that must stay sendable.
"""
from app.application.send_plan import needs_vacancy_refetch

# --- verbatim from the sheet, 2026-07-29 -----------------------------------

REFUSAL_121 = (
    "Не удалось извлечь содержание вакансии из предоставленной ссылки "
    "(контент не доступен). Пришлите текст объявления (роль, формат работы, "
    "условия, зарплата), и я кратко суммирую в нужном JSON."
)
REFUSAL_141 = (
    "Не могу извлечь содержимое вакансии по ссылке. Пришлите текст/скрин "
    "описания вакансии (роль, формат работы, условия и зарплата), и я кратко "
    "суммирую в нужном JSON."
)
REAL_119 = (
    "Роль: Backend Engineer. Формат работы: full-time, on-site в офисе в "
    "Алматы; динамичная высокоинтенсивная среда стартапа. Условия: архитектура "
    "и масштабирование data pipelines и систем приема/обработки больших объемов "
    "неструктурированных медиа-данных. Требования: 5+ лет опыта, опыт highload. "
    "Зарплата: competitive salary в USD + stock options."
)
REAL_148 = (
    "Ищут AI-Native Team Lead (Backend) в одной из крупнейших продуктовых "
    "компаний Казахстана для масштабного B2B-продукта. Задачи: руководить "
    "backend-командой и строить AI-продукты с фокусом на LLM, AI Agents, RAG "
    "и архитектуру. Формат работы: не указан. Зарплата: не указана."
)


def test_an_empty_column_needs_a_refetch():
    assert needs_vacancy_refetch("") is True
    assert needs_vacancy_refetch("   \n ") is True
    assert needs_vacancy_refetch(None) is True


def test_the_two_stored_refusals_are_recognised():
    assert needs_vacancy_refetch(REFUSAL_121) is True
    assert needs_vacancy_refetch(REFUSAL_141) is True


def test_real_vacancy_summaries_are_left_alone():
    assert needs_vacancy_refetch(REAL_119) is False
    assert needs_vacancy_refetch(REAL_148) is False


def test_the_phrase_deep_inside_a_real_vacancy_is_not_a_refusal():
    """A job description may discuss extraction; only an opening refusal counts."""
    body = (
        "Роль: Data Engineer. Условия: команда строит парсеры, и если из "
        "источника не удалось извлечь структуру, инженер разбирается почему. "
        "Формат работы: удалённо. Зарплата: не указана."
    )
    assert needs_vacancy_refetch(body) is False


def test_a_refusal_variant_the_model_might_word_differently():
    assert needs_vacancy_refetch("Не смог прочитать вакансию по ссылке.") is True
    assert needs_vacancy_refetch("Не получилось открыть страницу вакансии.") is True


# --- the refusals that opened nowhere near "не удалось" ----------------------
#
# Both verbatim from the run of 2026-07-29. Both passed the old detector, and
# both leads went out as `invited` with this text as the brief for the letter
# they will be sent once the person accepts.

REFUSAL_159 = (
    "Похоже, ссылка ведёт на пост в LinkedIn, но содержимое вакансии из URL "
    "недоступно. Пришлите текст объявления (роль, формат работы, условия и "
    "зарплата), и я кратко суммирую в JSON."
)
REFUSAL_160 = (
    "Нет данных о вакансии в сообщении: предоставлена только ссылка без "
    "описания роли, формата работы, условий и зарплаты."
)


def test_a_refusal_that_does_not_open_with_the_phrase_is_still_caught():
    assert needs_vacancy_refetch(REFUSAL_159) is True
    assert needs_vacancy_refetch(REFUSAL_160) is True


def test_a_refusal_that_leaks_the_output_format_is_caught():
    """No advert mentions the JSON it is supposed to be summarised into."""
    assert needs_vacancy_refetch("Дайте описание, и я суммирую в JSON.") is True


def test_an_english_refusal_is_caught_too():
    assert needs_vacancy_refetch("No job data in the message.") is True
    assert needs_vacancy_refetch("Please provide the job description.") is True


def test_a_real_advert_asking_for_a_cv_is_not_a_refusal():
    """"Пришлите резюме" is what a job ad says; "пришлите текст объявления" is
    what a model says when it has nothing to summarise. Only the second counts."""
    body = (
        "Ищут Go-разработчика. Формат работы: удалённо. Зарплата: 350 000 ₽. "
        "Пришлите резюме и ссылку на GitHub — ответим в течение дня."
    )
    assert needs_vacancy_refetch(body) is False


def test_a_real_advert_mentioning_json_is_not_a_refusal():
    body = (
        "Роль: Backend Engineer. Условия: сервис отдаёт JSON по REST, кандидат "
        "будет проектировать схемы и версионирование API. Зарплата: не указана."
    )
    assert needs_vacancy_refetch(body) is False


def test_a_real_advert_describing_a_data_gap_is_not_a_refusal():
    """"Нет данных" appears in adverts about data work; the refusal marker is the
    whole phrase "нет данных о вакансии"."""
    body = (
        "Роль: Data Engineer. Задачи: чинить пайплайны, когда нет данных за "
        "сутки, и следить за качеством витрин. Формат работы: гибрид."
    )
    assert needs_vacancy_refetch(body) is False
