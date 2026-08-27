"""Наши собственные подписи не решают, на каком языке говорит работодатель.

К тексту вакансии мы дописываем свои строки: «Зарплата: …» и «Локация: …»
(search_leads_repo._vacancy_text), «Компания: …» (vacancy_text.
extract_linkedin_vacancy). Все они по-русски, и в английской вакансии это
единственная кириллица — её хватает, чтобы `detect_language` сказал «ru».

Живой пример, реально отправленный лид #348 (замер 2026-08-26):

    Backend Engineer | Remote — Crossing Hurdles
    Локация: Европа, Ближний Восток и Африка (Удаленная работа)

Английская вакансия, русское письмо. И кириллица тут в основном НЕ в подписи, а
в значении: LinkedIn отдаёт локацию на языке нашей сессии, а сессия русская.
Поэтому из подсчёта выбрасывается строка целиком — переименование подписи в
«Location:» не починило бы ни одного из 14 испорченных лидов.

Из таблицы подписи никуда не деваются: их читает человек. Они просто не
голосуют за язык.
"""
from app.domain.candidate import Candidate
from app.domain.lead import COLUMNS
from app.domain.message_language import detect_language
from app.infrastructure.search_leads_repo import candidate_to_lead_row

LEAD_348 = ("Backend Engineer | Remote — Crossing Hurdles\n"
            "Локация: Европа, Ближний Восток и Африка (Удаленная работа)\n"
            "62/100: Backend контракт, требования Go/TS и API+DB; релевантно, "
            "но стек не приоритет и уровень неясен")


def test_the_localized_location_does_not_make_an_english_vacancy_russian():
    assert detect_language(LEAD_348) == "en"


def test_renaming_the_label_alone_would_not_have_helped():
    """Почему выбран этот путь, а не «перестать писать русские слова».

    Тот же лид с английской подписью «Location:» остаётся РУССКИМ: кириллица
    сидит в значении, которое перевела площадка, и переименование подписи её
    оттуда не убирает. На всех 492 строках листа (2026-08-26) переименование
    чинит 0 из 14 испорченных лидов, выбрасывание строки — все 14.

    Строка при этом перестаёт опознаваться как наша, и это правильно: с чужой
    подписью она уже не наша разметка, а текст, за который мы не отвечаем.
    """
    english_label = LEAD_348.replace("Локация:", "Location:")
    assert detect_language(english_label) == "ru"


def test_our_salary_and_location_go_on_one_line_and_both_are_dropped():
    """`_vacancy_text` склеивает факты в ОДНУ строку через запятую."""
    text = ("Senior Platform Engineer — Nordwind\n"
            "Зарплата: 90 000 ₽, Локация: Удалённо, Европа\n"
            "We run a Kubernetes platform for a few hundred services.")
    assert detect_language(text) == "en"


def test_our_company_label_from_a_refetched_linkedin_page_does_not_vote():
    """`extract_linkedin_vacancy` ставит «Компания: …» над телом вакансии.

    Решает эта подпись только на короткой странице — в длинном описании восьми
    букв не видно. Короткое описание LinkedIn отдаёт регулярно (одна строка
    «Remote, EU only» и ссылка на форму), и там подпись становится четвертью
    всех букв.
    """
    text = "QA Lead\nКомпания: Acme\nRemote, EU only."
    assert detect_language(text) == "en"


def test_a_russian_vacancy_is_not_talked_out_of_being_russian():
    """Обратная сторона чистки: своё объявление работодатель пишет сам.

    Если выбросить «Зарплата: …» и «Локация: …» из настоящего русского поста,
    остального текста обязано хватить. Проверка на 492 строках листа
    (2026-08-26) не нашла ни одной строки, которая от чистки уехала бы из
    русского в английский, но пусть это будет пришпилено.
    """
    text = ("Ищем backend-разработчика в продуктовую команду.\n"
            "Зарплата: 400 000 ₽\n"
            "Локация: Москва\n"
            "Работаем над сервисом планирования, много интеграций.")
    assert detect_language(text) == "ru"


def test_the_label_only_matters_at_the_start_of_a_line():
    """«Локация» посреди предложения — это слово работодателя, не наша подпись."""
    text = "Наша Локация: смотри ниже. Офис в центре, рядом метро, кофе за счёт компании."
    assert detect_language(text) == "ru"


def test_the_written_lead_row_carries_a_vacancy_no_label_can_russify():
    """Проверка у самого писателя строки, а не только у читателя.

    Кандидат ровно такой, каким его отдаёт поиск LinkedIn: английские title и
    company, локация — переведённая площадкой.
    """
    c = Candidate(platform="linkedin", kind="job",
                  url="https://www.linkedin.com/jobs/view/1",
                  title="Backend Engineer | Remote", company="Crossing Hurdles",
                  salary="", location="Европа, Ближний Восток и Африка (Удаленная работа)",
                  summary="62/100: Backend контракт, требования Go/TS и API+DB")
    row = candidate_to_lead_row(c, row_id=1, now="2026-08-26 12:00")
    vacancy = row[COLUMNS.index("Вакансия")]

    assert "Локация: Европа" in vacancy, "подпись обязана остаться — её читает человек"
    assert detect_language(vacancy) == "en"
