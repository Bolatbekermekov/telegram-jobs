"""Страницу ATS читаем, даже если человек что-то приписал от себя.

Гейт `_worth_reading` по умолчанию пускает только сообщение-голую-ссылку, и для
hh с вакансией LinkedIn это верно: у них есть свои каналы, которые перечитают
страницу позже. У ATS такого пути нет. Письмо пишется ДО того, как канал откроет
браузер, и пишется из колонки «Вакансия»; `needs_vacancy_refetch` спасает только
пустоту, нашу же разметку и отказ модели, а связный пересказ приписки «смотри,
вроде под тебя» он считает нормальным текстом и ссылку не перечитывает.

Ровно этот дефект чинили 2026-09-11 на лиде #930: письмо было написано из одной
строки нашей оценки, и таких в очереди оказалось 18 из 73.
"""
from app.application.extract_lead import ExtractLeadFromText

JOB = "https://boards.greenhouse.io/block/jobs/5406229008"
# Приписка заведомо длиннее `_MIN_MEANINGFUL_CHARS`: иначе её проглотит
# `is_link_only`, сообщение сойдёт за голую ссылку, и тест позеленеет, ничего не
# проверив. Именно так он и зеленел с первого захода.
ASIDE = ("Слушай, посмотри вот это, вроде прямо под тебя написано: они там на Go "
         "и Python пишут, команда небольшая, полностью удалённо, и вроде даже "
         f"релокацию обещают потом. {JOB}")


def _use_case(fetch):
    return ExtractLeadFromText(detector=lambda text: None, summarizer=None,
                               repo=None, fetcher=fetch)


def test_an_ats_link_is_read_even_with_prose_around_it():
    uc = _use_case(fetch=lambda url: "")
    assert uc._worth_reading(ASIDE, JOB) is True


def test_a_bare_link_is_still_read():
    uc = _use_case(fetch=lambda url: "")
    assert uc._worth_reading(JOB, JOB) is True


def test_an_hh_page_keeps_the_old_gate():
    """У hh свой канал и свой перечит: платить за фетч в 10-секундном бюджете незачем."""
    hh = "https://hh.ru/vacancy/123456789"
    uc = _use_case(fetch=lambda url: "")
    assert uc._worth_reading(ASIDE.replace(JOB, hh), hh) is False


def test_without_a_fetcher_nothing_is_read():
    assert _use_case(fetch=None)._worth_reading(ASIDE, JOB) is False
