"""Снятая вакансия должна называться снятой, а не «форма не распознана».

Замер 2026-08-24, прогон по Remocate: две вакансии из двенадцати были сняты, и
обе получили в таблицу заметку «форма не распознана». Формально верно — формы
там и правда нет, — но человека это отправляет искать поломку там, где чинить
нечего. Оба сайта говорят о себе прямо, просто не теми словами, которые ловило
прежнее правило:

    Toughbyte  — строка ровно «Closed» в тексте страницы, HTTP 200,
                 заголовок при этом обычный: «Full-Stack JavaScript Developer»
    YouHodler  — HTTP 404, заголовок «Not Found», первая строка «404»

Прежний шаблон требовал существительное перед состоянием («position closed»,
«page not found»), поэтому мимо прошли оба.
"""
from app.infrastructure.channels.external_apply import page_is_gone


def test_a_bare_closed_line_means_the_vacancy_is_gone():
    title = "Full-Stack JavaScript Developer - Toughbyte | Toughbyte"
    text = "Positions\nFor companies\nBlog\nSign in\nClosed\nview all positions\nRoles:"
    assert page_is_gone(title, text) is True


def test_a_not_found_title_means_the_page_is_gone():
    assert page_is_gone("Not Found", "404\nLooks like we lost\nthat page...\nGo Back Home") is True


def test_the_old_phrases_still_work():
    assert page_is_gone("", "Position Closed. Sorry, this position is no longer "
                            "accepting candidates.") is True
    assert page_is_gone("", "Эта вакансия закрыта. Попробуйте другие.") is True


def test_a_live_vacancy_is_not_gone():
    """Ради этого правило и держится узким: слово «closed» встречается в живых
    описаниях, и принять такую вакансию за снятую значит молча её потерять."""
    title = "Senior Backend Engineer — Acme"
    text = ("Senior Backend Engineer\nRemote\nApply now\n"
            "We work with closed-source SDKs and a closed beta programme.\n"
            "Applications are not closed to juniors.")
    assert page_is_gone(title, text) is False


def test_a_number_404_inside_prose_is_not_a_dead_page():
    """«404» в описании вакансии — это про обработку ошибок, а не про страницу."""
    text = ("Backend Engineer\nApply\nYou will handle 404 and 500 responses "
            "in our API gateway.")
    assert page_is_gone("Backend Engineer — Acme", text) is False


# --- вендоры, которые пишут о смерти СВОИМИ словами ---------------------------
# Замер 2026-08-27/28 видимым браузером на девяти снятых вакансиях (четыре Ashby
# с карточек remocate, пять Workday из поисковой выдачи). Обе формулировки —
# отдельными строками, и обе проходили мимо прежнего правила:
#
#   Ashby   `jobs.ashbyhq.com/adjoe/3610b4c7-…`  «Job not found»
#                                                «The job you requested was not found.»
#   Workday `bdx.wd1.myworkdayjobs.com/…/job/…`  «The page you are looking for doesn't exist.»
#
# «Job not found» не ловилось, потому что шаблон `page (not found|…)` требует
# перед состоянием слово «page», а `_GONE_LINE_RE` — чтобы строка была РОВНО
# «not found». У Workday между «page» и «doesn't exist» стоит целое придаточное.
# Обе строки — ЦЕЛЫЕ строки текста страницы, поэтому они и добавлены к правилу
# целой строки, а не к поиску по тексту: «job not found» внутри живого описания
# («handle job not found errors in the scheduler») ничего не отменяет.

def test_ashby_says_the_job_is_not_found():
    text = ("Job not found\n\nThe job you requested was not found.\n\n"
            "View all open positions\nPowered by\nPrivacy PolicySecurity")
    assert page_is_gone("Jobs", text) is True


def test_workday_says_the_page_does_not_exist():
    text = ("Skip to main content\nDecline\nAccept Cookies\nEnglish\nSign In\n"
            "Search for Jobs\nThe page you are looking for doesn't exist.\n"
            "Search for Jobs\nFollow Us\n© 2026 Workday, Inc. All rights reserved.")
    assert page_is_gone("Careers", text) is True


def test_the_same_words_inside_a_live_description_are_not_a_state():
    """Строка целиком — несущее требование: в описании эти слова живут спокойно."""
    text = ("Senior Backend Engineer\nApply\n"
            "You will handle job not found errors in the scheduler.\n"
            "If the page you are looking for doesn't exist, we render a 404.")
    assert page_is_gone("Senior Backend Engineer — Acme", text) is False
