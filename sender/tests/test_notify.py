from app.application.notify import format_duration, search_done_message


def test_message_with_new_candidates_says_they_are_already_queued():
    """Подтверждать нечего: с 2026-08-22 найденное сразу лежит лидами `new`.
    Звать в /show_vacancies больше нельзя — команды нет."""
    msg = search_done_message(["linkedin", "wellfound"], 15)
    assert "15" in msg
    assert "linkedin, wellfound" in msg
    assert "очереди на отправку" in msg
    assert "/show_vacancies" not in msg


def test_message_with_zero_says_nothing_new():
    msg = search_done_message(["wellfound"], 0)
    assert "wellfound" in msg
    assert "0" not in msg          # phrased as "ничего нового", not "+0"
    assert "ничего нового" in msg.lower()


# --- сколько времени ушло на каждую площадку ---------------------------------
#
# Поиск идёт по платформам последовательно и занимает минуты, а из сообщения
# нельзя было понять ни где он застрял, ни какая площадка потратила своё время
# впустую.

def test_each_platform_reports_its_own_time_and_yield():
    msg = search_done_message(["linkedin", "hh"], 7, timings=[
        ("linkedin", 92.4, 7),
        ("hh", 18.0, 0),
    ])
    assert "linkedin" in msg and "1 м 32 с" in msg and "+7" in msg
    assert "hh" in msg and "18 с" in msg


def test_a_platform_that_failed_is_named_as_such():
    """Иначе площадка, упавшая на первой секунде, выглядит как площадка, где
    просто не нашлось вакансий."""
    msg = search_done_message(["linkedin"], 0, timings=[("linkedin", 3.1, None)])
    assert "ошибка" in msg.lower()


def test_without_timings_the_message_is_the_old_one():
    """Замеры — необязательная деталь: без них сообщение обязано остаться
    прежним, иначе правка ломает всё, что его читает."""
    assert search_done_message(["linkedin"], 3) == search_done_message(
        ["linkedin"], 3, timings=None)


def test_duration_reads_naturally():
    assert format_duration(0.4) == "0 с"
    assert format_duration(18.0) == "18 с"
    assert format_duration(59.6) == "59 с"      # отсекаем, а не округляем
    assert format_duration(60) == "1 м 0 с"
    assert format_duration(92.4) == "1 м 32 с"
    assert format_duration(3675) == "1 ч 1 м"


# --- пауза площадки ----------------------------------------------------------
#
# Один и тот же текст уходит в двух направлениях: в консоль ноута (`make search`)
# и в Telegram тому, кто прислал команду из вкладки «Команды». У строки запроса в
# таблице колонки для причины нет, поэтому кроме этого текста человеку сказать
# нечем.

from app.application.notify import search_paused_message  # noqa: E402


def test_paused_message_names_the_platform_and_how_to_lift_the_pause():
    msg = search_paused_message(["linkedin"], [])

    assert "linkedin" in msg
    assert "PAUSED_PLATFORMS" in msg     # иначе отказ некуда деть, кроме как терпеть


def test_paused_message_says_what_is_still_being_searched():
    msg = search_paused_message(["linkedin"], ["remotive", "hh"])

    assert "linkedin" in msg
    assert "remotive, hh" in msg


def test_done_message_names_what_the_pause_left_out():
    """Без этой строки «Поиск завершён (remotive, hh)» читается как «искали
    везде»: выпавшая площадка в сообщении просто отсутствует."""
    msg = search_done_message(["remotive", "hh"], 3, paused=["linkedin"])

    assert "linkedin" in msg
    assert "паузе" in msg.lower()


def test_done_message_without_a_pause_is_unchanged():
    assert "паузе" not in search_done_message(["hh"], 1).lower()
