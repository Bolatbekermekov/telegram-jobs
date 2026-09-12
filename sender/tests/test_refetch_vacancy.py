"""Перечитка вакансии: дешёвым HTTP, а браузером — только где HTTP не пройдёт.

Замер 2026-09-11 на лиде #991 (`hh.ru/vacancy/136926142`): обычный GET получает
**403**, и это антибот hh, а не снятая вакансия. Тот же 403 приходит и на
`hh.kz`. Отсюда вся цепочка ломалась молча и навсегда:

* интейк читает ссылку с датацентрового IP Vercel — 403, «Вакансия» пустая;
* прогон на ноуте видит пустую колонку и перечитывает ссылку — тем же простым
  HTTP, и получает тот же 403;
* письмо писать не из чего, лид остаётся `new` и возвращается в каждый прогон.

То есть ЛЮБАЯ hh-ссылка, присланная боту руками, вставала намертво. Браузер эту
страницу открывает: у поиска по hh ровно такой запасной ход уже есть
(`HHSearcher.describe`), просто у цикла отправки не было открытой страницы.

Браузер тут не бесплатный — замер той же площадки даёт ~38 с против 0.6 с у
HTTP, — поэтому он и остаётся запасным ходом, а не основным путём.
"""
from app.application.refetch_vacancy import refetch_vacancy

HH = "https://hh.ru/vacancy/136926142"
OTHER = "https://boards.greenhouse.io/block/jobs/5406229008"


def test_a_readable_page_never_costs_a_browser():
    opened = []
    text = refetch_vacancy(HH, http_read=lambda u: "Описание вакансии",
                           browser_read=lambda u: opened.append(u) or "из браузера")
    assert text == "Описание вакансии"
    assert opened == [], "браузер стоит ~38 с против 0.6 с у HTTP"


def test_an_hh_page_blocked_by_the_antibot_is_read_with_the_browser():
    text = refetch_vacancy(HH, http_read=lambda u: "",
                           browser_read=lambda u: "Требования: Go, PostgreSQL")
    assert text == "Требования: Go, PostgreSQL"


def test_the_browser_is_asked_for_the_same_url():
    seen = []
    refetch_vacancy(HH, http_read=lambda u: "",
                    browser_read=lambda u: seen.append(u) or "текст")
    assert seen == [HH]


def test_other_platforms_do_not_get_a_browser_fallback():
    """403 — беда именно hh. У Greenhouse пустой ответ значит пустую страницу
    (Ashby и Workable отдают React-шелл), и браузер тут ничего не добавит, зато
    отнимет полминуты на каждом таком лиде."""
    opened = []
    text = refetch_vacancy(OTHER, http_read=lambda u: "",
                           browser_read=lambda u: opened.append(u) or "из браузера")
    assert text == ""
    assert opened == []


def test_without_a_browser_reader_the_answer_is_simply_empty():
    assert refetch_vacancy(HH, http_read=lambda u: "", browser_read=None) == ""


def test_a_broken_browser_is_not_a_crash():
    """Перечитка не обязана удаться: лид просто останется `new` до следующего раза."""
    def boom(url):
        raise RuntimeError("Chrome не запустился")

    assert refetch_vacancy(HH, http_read=lambda u: "", browser_read=boom) == ""
