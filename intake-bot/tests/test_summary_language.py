"""Пересказ вакансии пишется на языке оригинала, и язык этот считается кодом.

Замер 2026-08-26: из 35 строк листа с чисто английским оригиналом русскую
«Вакансию» получили все 35. Ни одного исключения — потому что просить модель
«сохрани язык оригинала» внутри целиком русского промпта бесполезно: модель
тянется к языку инструкции. Ровно это уже измерено на письме
(sender/app/domain/message_language.py, докстрока `language_rule`), поэтому
здесь тот же приём: язык называется прямо, а для английского — ещё и
по-английски.

Цена ошибки не в самой колонке: `vacancy_context` — это то, из чего ноут пишет
письмо, и по нему же он определяет язык, когда оригинала не хватает. Русский
пересказ английской вакансии уже отправил русский отклик на стажировку в
Бангалоре (лид #441, Easy Apply).
"""
from app.domain.message_language import summary_language, summary_language_rule

# Оригинал лида #481 — он реально стоял в очереди следующим.
BOOKING_EN = (
    "Senior Technology Product Manager. Booking.com is a global online travel "
    "platform that connects travelers with accommodations. You will own the "
    "roadmap for our partner-facing tooling and work with engineering, design "
    "and analytics. On-site in Amsterdam, relocation package provided."
)


def test_english_posting_gets_an_english_summary():
    assert summary_language(BOOKING_EN) == "en"


def test_russian_posting_stuffed_with_english_stack_stays_russian():
    """Обычная форма русского объявления: латиницы в нём больше, чем кириллицы.

    Порог кириллицы несимметричный (см. detect_language) именно поэтому.
    """
    text = ("Ищем Senior Backend Engineer в продуктовую команду. Будете "
            "развивать сервис планирования заказов и отвечать за его "
            "надёжность. Стек: Go, PostgreSQL, gRPC, Kubernetes, Docker, "
            "CI/CD, Prometheus, Grafana, Redis. Работа удалённая.")
    assert summary_language(text) == "ru"


def test_a_posting_in_neither_language_gets_english():
    """Пост на фарси (лид 181) пересказываем по-английски, а не имитируем фарси."""
    text = ("یک صندلی خالی کنار تیم ما هست؛ دنبال یک Back-End Developer "
            "باتجربه‌ایم. Go، PostgreSQL، API، Docker، تهران یا دورکاری کامل.")
    assert summary_language(text) == "en"


def test_a_bare_link_gives_no_language_at_all():
    """В ссылке три десятка латинских букв, и вакансией они не являются.

    Без этого голый адрес выглядел бы как английский текст — и мы бы велели
    модели писать по-английски про вакансию, которую никто не читал.
    """
    assert summary_language(
        "https://www.linkedin.com/jobs/view/senior-backend-engineer-4455783459") == ""


def test_two_words_forwarded_give_no_language():
    """«React dev» — это название роли: латиницей оно пишется на любом языке."""
    assert summary_language("React dev, пиши @ivan_hr") == ""
    assert summary_language("React dev, DM @ivan_hr") == ""


def test_nothing_at_all_gives_no_language():
    assert summary_language("") == ""
    assert summary_language(None) == ""
    assert summary_language("   \n\n ") == ""


def test_the_rule_names_the_language_and_repeats_english_in_english():
    """Приём взят у письма: английское указание в конце русского промпта
    работает сильнее, чем описание того же по-русски."""
    en = summary_language_rule("en")
    assert "англ" in en.lower()
    assert "English" in en
    ru = summary_language_rule("ru")
    assert "русск" in ru.lower()
    assert "English" not in ru


def test_no_language_means_no_addition_to_the_prompt():
    """Языка не знаем — значит и не называем его.

    Написать «пиши по-русски» над двумя английскими словами значит заказать
    перевод и выдать выдуманный язык за решение. Промпт остаётся как был:
    он русский, и без сигнала пересказ выйдет русским — тот же ответ, который
    на пустом тексте даёт ноут (detect_language("") == "ru").
    """
    assert summary_language_rule("") == ""
