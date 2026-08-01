"""На каком языке писать: определяем по тексту вакансии, а не надеемся на модель."""
from app.domain.message_language import detect_language, language_rule


def test_russian_vacancy():
    assert detect_language(
        "Ищем backend-разработчика в продуктовую команду. Опыт от 3 лет.") == "ru"


def test_english_vacancy():
    assert detect_language(
        "We are looking for a Senior Backend Engineer to own our scheduling "
        "service. Requirements: 3+ years with Go, strong SQL.") == "en"


def test_russian_vacancy_stuffed_with_english_stack_stays_russian():
    """Реальная форма русского объявления: латиницы в нём больше, чем кириллицы.

    Простое большинство букв увело бы такую вакансию в английский, поэтому
    порог несимметричный.
    """
    text = ("Ищем Senior Backend Engineer в продуктовую команду. Будете "
            "развивать сервис планирования заказов и отвечать за его "
            "надёжность. Стек: Go, PostgreSQL, gRPC, Kubernetes, Docker, "
            "CI/CD, Prometheus, Grafana, Redis, RabbitMQ, ClickHouse, "
            "Terraform, GitHub Actions, k6, pytest, FastAPI. Работа удалённая.")
    assert detect_language(text) == "ru"


def test_english_vacancy_with_a_cyrillic_name_stays_english():
    """Русское имя рекрутёра в английском объявлении не делает его русским."""
    text = ("We are looking for a Senior Backend Engineer to own our fleet "
            "scheduling service. Requirements: 3+ years with Go, strong SQL, "
            "experience with REST and gRPC APIs, Docker and CI. Remote within "
            "the EU. Contact: Анна Вебер, Talent Partner.")
    assert detect_language(text) == "en"


def test_relevance_score_note_does_not_flip_an_english_vacancy():
    """Поисковик приклеивает к вакансии свою оценку, всегда по-русски.

    Из-за неё лид 13 (английская вакансия на wellfound) получил русское письмо.
    """
    text = ("Front End lead/ developer\nRemote onlyEverywhereNo equity\n"
            "POSTED 3 DAYS AGO — 70/100: Подходит по стеку и remote, но уровень "
            "явно не intern/junior, а мидл/lead")
    assert detect_language(text) == "en"


def test_a_posting_in_neither_language_gets_english():
    """На пост на фарси (лид 181) отвечаем по-английски, а не имитируем фарси."""
    text = ("یک صندلی خالی کنار تیم ما هست؛ دنبال یک Back-End Developer "
            "باتجربه‌ایم. Go، PostgreSQL، API")
    assert detect_language(text) == "en"


def test_empty_vacancy_falls_back_to_russian():
    """Пустой текст это не «английская вакансия», а отсутствие сигнала.

    Поток у нас в основном русскоязычный (Telegram, hh), поэтому без сигнала
    остаёмся на русском, а не уводим письмо в английский на ровном месте.
    """
    assert detect_language("") == "ru"
    assert detect_language(None) == "ru"
    assert detect_language("   \n\n  ") == "ru"


def test_the_rule_names_the_language_the_model_must_use():
    assert "англ" in language_rule("en").lower()
    assert "English" in language_rule("en")
    assert "русск" in language_rule("ru").lower()
    assert "English" not in language_rule("ru")
