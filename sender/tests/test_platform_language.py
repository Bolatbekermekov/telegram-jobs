"""У hh.ru язык вакансии известен заранее, и по тексту его определять нечем.

hh.ru — русскоязычный сайт: объявления и переписка на нём по-русски. Замер
2026-08-26 по всем 106 hh-строкам листа не нашёл ни одной англоязычной вакансии.

А текста, по которому это можно было бы увидеть, у hh-лида нет:

* search-лид площадки хранит только заголовок, компанию и НАШУ строку локации.
  «QA Engineer Middle (mobile) — Gaijin Games, Локация: Serbia» (#466) считался
  русским ровно из-за слова «Локация»: 15.2% кириллицы при пороге 15%. Убери
  нашу подпись из подсчёта — и 22 русские вакансии hh получили бы английские
  письма;
* у лида из телеграма в «Исходном тексте» лежит ссылка, и её букв
  (`hhtmFromLabel`, `suitable_vacancies`, `utm_source`) хватает, чтобы
  `language_source` ей поверил и прочитал вакансию как английскую. Так уже
  происходит с 17 строками — #55, #101, #168, #200 и другими; ещё 5 (#41, #44,
  #462, #464, #465) уезжают в английский по одному латинскому заголовку.

Поэтому площадка отвечает за свой язык сама, а текст спрашивают только там, где
он о чём-то говорит.
"""
from app.domain.lead import Lead
from app.domain.message_language import language_for


def _lead(platform, vacancy_context="", raw_text=""):
    return Lead(row=2, lead_id="1", platform=platform, target="https://x",
                vacancy_context=vacancy_context, raw_text=raw_text, status="new")


def test_an_hh_lead_whose_stub_is_all_latin_still_gets_russian():
    # Лид #466: кроме нашей подписи в строке нет ни одной кириллической буквы.
    lead = _lead("hh", raw_text=(
        "QA Engineer Middle (mobile) — Gaijin Games\nЛокация: Serbia\n"
        "74/100: Middle QA mobile: опыт релевантен"))
    assert language_for(lead) == "ru"


def test_an_hh_lead_whose_source_is_a_tracking_link_still_gets_russian():
    # Лид #101: «Исходный текст» это ссылка, и её слов хватает на «английский».
    lead = _lead("hh",
                 vacancy_context="Frontend-разработчик. Формат работы: удалённо.",
                 raw_text=("https://hh.ru/vacancy/134940090"
                           "?hhtmFromLabel=suitable_vacancies&hhtmFrom=vacancy"))
    assert language_for(lead) == "ru"


def test_hh_is_named_by_the_platform_column_case_insensitively():
    assert language_for(_lead("HH", raw_text="Senior Backend Engineer, Go")) == "ru"


def test_other_platforms_are_still_decided_by_the_text():
    """Правило про hh не должно тянуть на английские вакансии остальных площадок.

    Лид #348: та самая английская вакансия с русской локацией от LinkedIn.
    """
    lead = _lead("linkedin", raw_text=(
        "Backend Engineer | Remote — Crossing Hurdles\n"
        "Локация: Европа, Ближний Восток и Африка (Удаленная работа)\n"
        "62/100: Backend контракт, требования Go/TS и API+DB"))
    assert language_for(lead) == "en"


def test_a_russian_post_on_another_platform_stays_russian():
    lead = _lead("telegram", raw_text=(
        "Ищем инженера по тестированию в продуктовую команду, удалённо. "
        "Нужен опыт от двух лет и знание Python."))
    assert language_for(lead) == "ru"
