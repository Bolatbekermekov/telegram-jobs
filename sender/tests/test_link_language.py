"""Адрес — не текст работодателя, и языка вакансии он не доказывает.

`language_source` считает буквы, чтобы понять, есть ли в оригинале слова, по
которым виден язык. Считались они В ТОМ ЧИСЛЕ ВНУТРИ ССЫЛОК, а трекинговый
адрес — это три десятка латинских букв:

    https://hh.ru/vacancy/136486822?query=golang+developer
    &hhtmFrom=vacancy_search_list&hhtmFromLabel=suitable_vacancies

Порог доверия он проходит с запасом и выдаёт себя за «текст работодателя на
английском». Замер 2026-08-27 по 492 строкам листа: на не-hh площадках у 73
строк больше половины букв, решающих язык, лежит внутри адреса. У hh это уже
закрыто отдельным правилом (`_RUSSIAN_LANGUAGE_PLATFORMS`), у остальных — нет.

Percent-кодированная кириллица в адресе поста LinkedIn
(`_%D0%B8%D1%89%D1%83-fullstack-qa-engineer-…` — это «ищу»), пока её не
раскодировать, читается как латиница и голосует за английский особенно охотно:
именно русские посты попадают в LinkedIn-адрес в таком виде.
"""
from app.domain.lead import Lead
from app.domain.message_language import (
    detect_language,
    language_for,
    language_source,
)

# Лид #101: hh-строка из телеграма, в «Исходном тексте» один адрес.
HH_TRACKING_URL = ("https://hh.ru/vacancy/136486822?query=golang+developer"
                   "&hhtmFrom=vacancy_search_list"
                   "&hhtmFromLabel=suitable_vacancies")
# Лид #143: пост LinkedIn, слаг — латиница (хештеги и английский заголовок).
LINKEDIN_POST_URL = (
    "https://www.linkedin.com/posts/vladislav-shuteev-84330a159"
    "_im-hiring-a-senior-python-engineer-for-manychat-share-"
    "7481333727407734784-swLy/?utm_source=share&utm_medium=member_ios"
    "&rcm=ACoAAEAtyR8BHJbjBMhFRHmhkmUsMVa6OoltAbY")
# Лид #136: тот же пост LinkedIn, но слаг percent-кодирует кириллицу — «ищу
# fullstack qa engineer в высоконагруженный».
LINKEDIN_CYRILLIC_URL = (
    "https://www.linkedin.com/posts/ezhiltsov"
    "_%D0%B8%D1%89%D1%83-fullstack-qa-engineer-%D0%B2-%D0%B2%D1%8B%D1%81"
    "%D0%BE%D0%BA%D0%BE%D0%BD%D0%B0%D0%B3%D1%80%D1%83%D0%B6%D0%B5%D0%BD"
    "%D0%BD%D1%8B%D0%B9-share-7485228700209352704-9Py-/")


def _lead(vacancy_context="", raw_text="", platform="linkedin"):
    return Lead(row=2, lead_id="143", platform=platform, target="https://x",
                vacancy_context=vacancy_context, raw_text=raw_text, status="new")


def test_a_bare_tracking_link_is_not_an_english_vacancy():
    """`hhtmFromLabel`, `suitable_vacancies`, `utm_source` — это не слова людей.

    Без букв ответ уже определён и означает «сигнала нет», а не «английский»
    (см. `test_nothing_left_after_the_links_is_not_a_language`).
    """
    assert detect_language(HH_TRACKING_URL) == "ru"


def test_a_link_does_not_get_the_original_past_the_trust_threshold():
    """Порог в 40 букв спрашивает, есть ли оригиналу что сказать о языке.

    Лид #143: в «Исходном тексте» один адрес поста, и его 120 латинских букв
    порог проходили. Значит, колонку «Вакансия» — единственный настоящий текст
    у этой строки — никто не спрашивал.
    """
    lead = _lead("Ищут Senior Python Engineer для ManyChat. Формат работы: "
                 "не указан. Зарплата: не указана.",
                 raw_text=LINKEDIN_POST_URL)
    assert language_source(lead) == lead.vacancy_context
    assert language_for(lead) == "ru"


def test_percent_encoded_cyrillic_in_an_address_does_not_vote_for_english():
    """Лид #136: русский пост, чей адрес выглядит латиницей.

    `%D0%B8%D1%89%D1%83` это «ищу», но пока это байты в адресе — это буквы D,
    B, D, D, D. Русские посты попадают в адрес LinkedIn именно так, поэтому
    голос адреса не просто шумный, а систематически смещён в английский.
    """
    lead = _lead("Ищу FullStack QA Engineer в высоконагруженный FinTech-продукт. "
                 "Несколько команд — несколько вакансий.",
                 raw_text=LINKEDIN_CYRILLIC_URL)
    assert language_for(lead) == "ru"


def test_the_address_is_dropped_whole_and_never_decoded():
    """Обратная сторона: раскодировать адрес — тоже дать ему голос.

    Соблазн понятен — у 28 из 67 изменившихся строк листа кириллица в адресе
    есть, и она права. Но у остальных 39 слаг латинский НЕ потому, что пост
    английский: LinkedIn кладёт в адрес хештеги, а их пишут латиницей и над
    русским текстом (`_intexsoft-hiring-itjobs-`, `_nlp-ai-auoauo-`,
    `_igaming-node-react-` — всё это посты, начинающиеся с «Всем привет!»).
    Раскодированный адрес чинит 28 и продолжает врать про 39; выброшенный не
    врёт ни про одну. Поэтому английская вакансия с таким адресом обязана
    остаться английской.
    """
    text = ("We are looking for a Senior Backend Engineer to own our scheduling "
            "service. Requirements: 3+ years with Go, strong SQL and REST.\n"
            + LINKEDIN_CYRILLIC_URL)
    assert detect_language(text) == "en"


def test_the_employers_own_words_around_a_link_still_count():
    """Чистится адрес, а не строка с адресом: рядом с ним лежит текст поста."""
    text = ("Ищем backend-разработчика в продуктовую команду, удалённо.\n"
            "Подробности и отклик: " + LINKEDIN_POST_URL)
    assert detect_language(text) == "ru"


def test_a_link_only_lead_is_not_automatically_russian():
    """Снятие адреса возвращает вопрос колонке «Вакансия», а не отвечает за неё.

    Лид #141 из листа: в «Исходном тексте» один адрес поста, а в колонке —
    текст самого поста, по-английски. Ответ обязан остаться английским. Это не
    случайность и не везение: колонку интейк пишет по ТЕКСТУ СТРАНИЦЫ
    (extract_lead._vacancy_source отдаёт page_text, когда сообщение — одна
    ссылка), а с a7c65cd — на языке оригинала. Строкам, заведённым раньше,
    достался русский пересказ, и вот они после этой правки уезжают в русский:
    разбор глазами 2026-08-27 насчитал таких 19 из 67 изменившихся (все
    LinkedIn, ни одной со статусом `new`). Лечится это не голосом адреса, а
    перечитыванием страницы.
    """
    lead = _lead("Excited to share that I've joined 42 as HR Director.\n\n"
                 "42 is an AI research company building an autonomous AI "
                 "Scientist — a system designed to automate scientific work.",
                 raw_text=("https://www.linkedin.com/posts/anastasiya-lipkina"
                           "_excited-to-share-that-ive-joined-42-as-hr-ugcPost-"
                           "7474748735390900225-jjeN/?utm_source=share"))
    assert language_for(lead) == "en"


def test_cyrillic_written_into_the_address_as_is_does_not_vote_either():
    """Лид #245: `ru.linkedin.com/posts/…_мы-ищем-qa-engineer-…`, колонка пуста.

    Кириллица в адресе бывает и не закодированной, и правило для неё то же
    самое: адрес — это адрес. Ответ («ru») тот же, но теперь он значит
    «сигнала нет», а не «пост русский, судя по ссылке», — и на английском
    адресе он поэтому не перевернётся.
    """
    lead = _lead("", raw_text=("https://ru.linkedin.com/posts/inna-dobrovolskaia"
                               "-bb6567173_мы-ищем-qa-engineer-требуемые-навыки"
                               "-activity-7491115161144041472-XLtA"))
    assert language_for(lead) == "ru"


def test_nothing_left_after_the_links_is_not_a_language():
    """Пустой остаток — это отсутствие сигнала, и ответ на него уже определён.

    Интейк на том же вопросе (`summary_language` -> "") не добавляет в промпт
    НИЧЕГО, промпт остаётся русским и пересказ выходит русским. Ноут обязан
    сказать то же самое, иначе колонка «Вакансия» и письмо по ней разъедутся.
    """
    assert detect_language(HH_TRACKING_URL) == detect_language("")
    assert detect_language(LINKEDIN_POST_URL) == "ru"
    assert detect_language("https://t.me/some_hr_channel/12345") == "ru"


def test_a_scheme_less_link_counts_as_a_link_too():
    """Телеграм и телефон отдают адрес без схемы — `_URL_RE` это уже знает.

    Определение ссылки здесь не своё: оно взято у `vacancy_text`, где на нём
    держится `is_link_only`, и настроено на живых сообщениях (замер 2026-08-22,
    вакансия X-FLOW 4455783459).
    """
    assert detect_language(
        "linkedin.com/jobs/view/senior-fullstack-engineer-at-x-flow-4455783459"
    ) == "ru"
