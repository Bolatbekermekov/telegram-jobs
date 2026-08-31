"""Защита от повторной отправки одному адресу.

Числа в тестах не выдуманы: они замерены на живом листе 2026-08-03, где на
113 уникальных получателей нашлось 10 повторов. Разборы пар — в комментариях
к конкретным тестам.
"""
from datetime import datetime

from app.domain.lead import Lead, STATUS_SKIPPED
from app.domain.outreach_history import (
    SentRecord,
    duplicate_reason,
    normalize_address,
    vacancy_posting,
    vacancy_similarity,
)

NOW = datetime(2026, 8, 3, 12, 0)


def _lead(target, vacancy="", platform="telegram"):
    return Lead(row=2, lead_id="1", platform=platform, target=target,
                vacancy_context=vacancy, raw_text=vacancy, status="new")


def _sent(target, vacancy, sent_at, platform="telegram"):
    return SentRecord(platform=platform, address=normalize_address(target),
                      vacancy=vacancy, sent_at=sent_at)


# --- нормализация адреса ----------------------------------------------------

def test_telegram_handle_forms_collapse_to_one_address():
    """Один и тот же человек приходит то хендлом, то ссылкой."""
    forms = ["@perovvaa", "perovvaa", "t.me/perovvaa",
             "https://t.me/perovvaa", "https://t.me/perovvaa/",
             "  @PerovvAA  "]
    assert len({normalize_address(f) for f in forms}) == 1


def test_email_case_does_not_create_a_second_address():
    assert normalize_address("HR@Bellintegrator.RU") == normalize_address("hr@bellintegrator.ru")


def test_tracking_parameters_do_not_create_a_second_address():
    """LinkedIn клеит к ссылке trk/trackingid, и они меняются от показа к показу."""
    a = "https://www.linkedin.com/jobs/view/4428534200/?trk=flagship3_search_srp_jobs"
    b = "https://www.linkedin.com/jobs/view/4428534200/?ebp=not_eligible&trackingid=xyz"
    assert normalize_address(a) == normalize_address(b)


def test_different_people_stay_different():
    assert normalize_address("@perovvaa") != normalize_address("@amhrann1")


def test_blank_address_normalizes_to_empty():
    assert normalize_address("") == ""
    assert normalize_address(None) == ""
    assert normalize_address("   ") == ""


# --- похожесть вакансий -----------------------------------------------------

def test_the_same_vacancy_reposted_scores_above_the_threshold():
    """Лиды 107 и 186: одна вакансия preax, переписанная моделью заново.

    Замерено: containment 0.540. Порог 0.25.
    """
    a = ("Роль: стажер Frontend-разработчик (React). Формат работы: удаленно, "
         "обучение в гибком графике, задачи по вёрстке и интеграции с API.")
    b = ("Роль: стажер Frontend-разработчик (React). Формат: удаленно, гибкий "
         "график, минимум 3 часа практики в день, вёрстка и работа с API.")
    assert vacancy_similarity(a, b) >= 0.25


def test_two_different_openings_from_one_recruiter_score_below_the_threshold():
    """Лиды 175 и 184: тот же рекрутёр, но это две РАЗНЫЕ позиции.

    Замерено: containment 0.167. Такое блокировать нельзя.
    """
    a = ("Fullstack-разработчик (NestJS + React/Next.js). Формат: офис, Астана. "
         "График 6/1, оформление по договору.")
    b = ("Backend Developer (TypeScript/Node.js/NestJS, также Python/FastAPI "
         "плюсом). Удалённая работа, международная команда.")
    assert vacancy_similarity(a, b) < 0.25


def test_similarity_is_undefined_when_a_vacancy_is_missing():
    """Лид 208 пришёл с пустой «Вакансией» — сравнивать не с чем."""
    assert vacancy_similarity("", "Senior Frontend Developer") is None
    assert vacancy_similarity("Senior Frontend Developer", None) is None


def test_similarity_survives_a_large_length_difference():
    """Лиды 75 и 171: второй пост длиннее первого почти вдвое.

    Именно здесь Jaccard проваливался (0.142 против фонового максимума 0.216),
    поэтому мера — containment, а не Jaccard.
    """
    short = "Роль: AI-оптимизатор, внедрение AI-решений в бизнес-процессы компании."
    long = ("Роль: AI-оптимизатор (джун-мидл), внедрение AI-решений в "
            "бизнес-процессы компании. Формат работы: офис или гибрид, Кипр, "
            "готовность к релокации, оформление, страховка, помощь с визой.")
    assert vacancy_similarity(short, long) >= 0.25


# --- решение об отправке ----------------------------------------------------

def test_first_contact_with_an_address_goes_out():
    assert duplicate_reason(_lead("@newguy", "Go разработчик"), [], NOW, 5) is None


def test_the_same_vacancy_is_never_sent_twice_however_long_the_gap():
    """Главный вывод разбора: три из четырёх настоящих дублей имели разрыв
    9-10 дней, то есть окно в 5 дней их бы пропустило."""
    history = [_sent("@amhrann1",
                     "Роль: AI-оптимизатор, внедрение AI-решений в бизнес-процессы.",
                     datetime(2026, 5, 1, 10, 0))]
    lead = _lead("@amhrann1",
                 "Роль: AI-оптимизатор (джун-мидл), внедрение AI-решений в "
                 "бизнес-процессы компании, офис или гибрид, Кипр.")
    got = duplicate_reason(lead, history, NOW, 5)
    assert got is not None
    status, note = got
    assert status == STATUS_SKIPPED
    assert "already applied" in note


def test_a_different_vacancy_inside_the_window_waits():
    """Лиды 175 и 184: разные позиции, но разрыв в один день — это спам."""
    history = [_sent("@hellok1tty0",
                     "Fullstack-разработчик (NestJS + React/Next.js), офис Астана.",
                     datetime(2026, 8, 2, 10, 0))]
    lead = _lead("@hellok1tty0",
                 "Backend Developer (TypeScript/Node.js/NestJS), удалённо.")
    got = duplicate_reason(lead, history, NOW, 5)
    assert got is not None
    assert got[0] == STATUS_SKIPPED
    assert "already applied" in got[1]


def test_a_different_vacancy_outside_the_window_goes_out():
    """Тот же рекрутёр через месяц с другой вакансией — это нормальный отклик."""
    history = [_sent("@hellok1tty0",
                     "Fullstack-разработчик (NestJS + React/Next.js), офис Астана.",
                     datetime(2026, 7, 1, 10, 0))]
    lead = _lead("@hellok1tty0",
                 "Backend Developer (TypeScript/Node.js/NestJS), удалённо.")
    assert duplicate_reason(lead, history, NOW, 5) is None


def test_another_address_is_not_blocked_by_someone_elses_history():
    history = [_sent("@amhrann1", "Роль: AI-оптимизатор.", datetime(2026, 8, 2, 10, 0))]
    assert duplicate_reason(_lead("@perovvaa", "Go разработчик"), history, NOW, 5) is None


def test_the_same_handle_on_another_platform_is_another_person():
    history = [_sent("@ivan", "Go разработчик", datetime(2026, 8, 2, 10, 0),
                     platform="telegram")]
    lead = _lead("@ivan", "Go разработчик", platform="threads")
    assert duplicate_reason(lead, history, NOW, 5) is None


def test_a_send_with_no_recorded_date_blocks():
    """Семь строк в листе — `invited` в LinkedIn без даты: приглашение висит,
    ответа нет. Писать туда ещё раз, пока непонятно когда писали, нельзя."""
    history = [_sent("@somebody", "Go разработчик", None)]
    got = duplicate_reason(_lead("@somebody", "Совсем другая вакансия"), history, NOW, 5)
    assert got is not None
    assert got[0] == STATUS_SKIPPED


def test_a_lead_with_no_vacancy_text_falls_back_to_the_window():
    """Лид 208: «Вакансия» пустая, сравнивать не с чем — решает только время."""
    history = [_sent("@jakson_vill", "Senior Frontend Developer в Tango",
                     datetime(2026, 8, 3, 0, 15))]
    assert duplicate_reason(_lead("@jakson_vill", ""), history, NOW, 5) is not None

    old = [_sent("@jakson_vill", "Senior Frontend Developer в Tango",
                 datetime(2026, 6, 1, 0, 15))]
    assert duplicate_reason(_lead("@jakson_vill", ""), old, NOW, 5) is None


def test_a_blank_target_is_not_treated_as_a_duplicate():
    """Пустой «Источник» — забота skip_reason, а не наша: иначе все пустые
    строки схлопнутся в один «адрес» и заблокируют друг друга."""
    history = [_sent("", "Go разработчик", datetime(2026, 8, 2, 10, 0))]
    assert duplicate_reason(_lead("", "Go разработчик"), history, NOW, 5) is None


def test_the_note_names_the_lead_we_already_wrote_to():
    """Заметку читает человек: без id он не поймёт, куда смотреть."""
    history = [SentRecord(platform="telegram", address="amhrann1",
                          vacancy="Роль: AI-оптимизатор, внедрение AI-решений.",
                          sent_at=datetime(2026, 8, 2, 10, 0), lead_id="75")]
    got = duplicate_reason(_lead("@amhrann1", "Роль: AI-оптимизатор, внедрение AI."),
                           history, NOW, 5)
    assert got is not None
    assert "75" in got[1]


# --- одно объявление у одного работодателя, разные адреса ---------------------
#
# Замер листа 2026-08-29: LLC СП Солюшен получил одну и ту же «AI-разработчик
# (Python) Junior / Middle» ДВАДЦАТЬ ЧЕТЫРЕ раза за три дня. У hh отклик уходит
# на вакансию, то есть «получатель» — это ссылка, а копии по городам имеют
# честно разные ссылки. Правило по адресу их не видело.

_V = "AI-разработчик (Python) Junior / Middle — LLC СП Солюшен\nЛокация: Омск\n78/100: ок"
_V_OTHER_CITY = ("AI-разработчик (Python) Junior / Middle — LLC СП Солюшен\n"
                 "Локация: Тула\n82/100: ок")


def _hh_lead(url, vacancy, platform="hh", lead_id="2"):
    return Lead(row=2, lead_id=lead_id, platform=platform, target=url,
                vacancy_context=vacancy, raw_text="", status="new", sent_at=None)


def _hh_past(url, vacancy, platform="hh", lead_id="1"):
    return SentRecord(platform=platform, address=normalize_address(url),
                      vacancy=vacancy, sent_at=datetime(2026, 8, 26, 10, 0),
                      lead_id=lead_id)


def test_the_same_posting_at_another_url_is_not_written_again():
    verdict = duplicate_reason(
        _hh_lead("https://hh.ru/vacancy/136551284", _V_OTHER_CITY),
        [_hh_past("https://hh.ru/vacancy/136551281", _V)],
        datetime(2026, 8, 29, 12, 0), window_days=14)

    assert verdict is not None
    status, note = verdict
    assert status == STATUS_SKIPPED
    assert "то же объявление" in note
    assert "#1" in note          # человеку видно, какой лид повторяется


def test_another_role_at_the_same_employer_still_goes():
    other = "Go-разработчик — LLC СП Солюшен\nЛокация: Омск\n80/100: ок"
    assert duplicate_reason(
        _hh_lead("https://hh.ru/vacancy/2", other),
        [_hh_past("https://hh.ru/vacancy/1", _V)],
        datetime(2026, 8, 29, 12, 0), window_days=14) is None


def test_the_same_title_at_another_employer_still_goes():
    other = "AI-разработчик (Python) Junior / Middle — Другая Компания\n78/100: ок"
    assert duplicate_reason(
        _hh_lead("https://hh.ru/vacancy/2", other),
        [_hh_past("https://hh.ru/vacancy/1", _V)],
        datetime(2026, 8, 29, 12, 0), window_days=14) is None


def test_another_platform_is_not_blocked_by_it():
    assert duplicate_reason(
        _hh_lead("https://linkedin.com/jobs/view/9", _V, platform="linkedin"),
        [_hh_past("https://hh.ru/vacancy/1", _V)],
        datetime(2026, 8, 29, 12, 0), window_days=14) is None


def test_the_old_combined_format_is_not_parsed_at_all():
    """«AI Intern — 92/100: …» — тут за работодателя принималась бы проза."""
    old = "AI Intern — 92/100: AI Intern, работа с LLM — хорошо совпадает с поиском"
    assert vacancy_posting(old) is None


def test_a_prose_summary_without_a_head_line_is_not_parsed():
    assert vacancy_posting("Ищут Frontend-разработчика (React / TypeScript).") is None


def test_a_long_tail_is_not_taken_for_an_employer():
    long_tail = "Роль — " + "очень длинное описание вместо названия компании" * 2
    assert vacancy_posting(long_tail) is None
