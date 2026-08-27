"""Язык письма берётся у работодателя, а не у нашего пересказа.

Замер 2026-08-26, лид #481 (реально стоял в очереди). Оригинал вакансии
английский — «Booking.com is a global online travel platform…», — а колонка
«Вакансия» хранит русский пересказ: интейк суммирует русским промптом, не
требуя сохранить язык оригинала (проверено: 35 из 35 английских вакансий
получили русское описание).

Язык при этом определялся ПО ПЕРЕСКАЗУ, потому что он стоял первым в
`vacancy_context or raw_text`. Итог: письмо в Booking.com в Амстердаме ушло бы
по-русски. Так уже случилось с лидом #441 — отклик на стажировку в Бангалоре
подан через Easy Apply с русским текстом.

Порядок здесь обратный: сначала оригинал, и только если в нём не на чем
определять — пересказ. Для hh-строки в «Исходном тексте» лежит одна ссылка, для
search-лида оба поля совпадают, поэтому запасной вариант обязателен.
"""
from app.domain.lead import Lead
from app.domain.message_language import language_source

BOOKING_EN = ("Senior Technology Product Manager\nBooking.com is a global online "
              "travel platform that connects travelers with accommodations.")
BOOKING_RU = ("Роль: Senior Technology Product Manager в Booking.com. "
              "Формат работы: on-site (Амстердам, Нидерланды).")


def _lead(vacancy_context="", raw_text=""):
    return Lead(row=2, lead_id="481", platform="linkedin", target="https://x",
                vacancy_context=vacancy_context, raw_text=raw_text, status="new")


def test_original_wins_over_our_russian_summary():
    assert language_source(_lead(BOOKING_RU, BOOKING_EN)) == BOOKING_EN


def test_summary_used_when_the_original_is_just_a_link():
    # hh-строка: в «Исходном тексте» лежит только адрес вакансии, букв нет.
    lead = _lead("Роль: Go-разработчик. Москва.", "https://hh.ru/vacancy/136486822")
    assert language_source(lead) == "Роль: Go-разработчик. Москва."


def test_summary_used_when_the_original_is_empty():
    assert language_source(_lead("Роль: QA. Астана.", "")) == "Роль: QA. Астана."


def test_original_too_short_falls_back_to_the_summary():
    # «Frontend Engineer» — две трети букв это название роли, оно одинаково
    # выглядит на обоих языках и языка не доказывает.
    lead = _lead("Роль: Frontend-разработчик, удалённо, опыт 2+ года.", "React dev")
    assert language_source(lead) == "Роль: Frontend-разработчик, удалённо, опыт 2+ года."


def test_both_empty_gives_empty():
    assert language_source(_lead("", "")) == ""
