"""Поле сообщения в чате hh: замер 2026-08-27, разметка переехала.

Прогон 2026-08-27 дал подряд «ОТКЛИК ОТПРАВЛЕН, НО СОПРОВОДИТЕЛЬНОЕ ПИСЬМО НЕ
ДОШЛО». Отладочный снимок (`sender/.hh_chat_debug/hh_chat_no_message_box.html`)
показал причину: композер РАСКРЫЛСЯ — «Add a cover letter» сработала, поле на
экране есть, — но прежнего имени у него больше нет.

    было:  <textarea data-qa="chatik-new-message-text">   — 0 совпадений в снимке
    стало: <div data-qa="chatik-message-input">
             <textarea data-qa="text-input" placeholder="Message"
                       class="magritte-text-input___3AFO4_1-1-5">

hh переехал на дизайн-систему magritte, и у поля теперь родовое имя
`text-input`. Само по себе оно НЕ годится: такой `data-qa` на странице носит
любой текстовый ввод, включая поиск по вакансиям в шапке. Поэтому цепляемся за
контейнер чата, а внутри уже берём textarea.

Старое имя оставлено первым: hh раскатывает интерфейс не всем сразу, и пока
часть сессий видит прежнюю разметку, потерять её значит поменять одну поломку
на другую.
"""
from app.infrastructure.channels.headhunter import SEL_CHAT_MSG


def test_the_new_composer_is_covered():
    assert "chatik-message-input" in SEL_CHAT_MSG


def test_the_old_composer_is_still_covered():
    # hh катит интерфейс частями; пока старая разметка встречается — она наша.
    assert "chatik-new-message-text" in SEL_CHAT_MSG


def test_a_bare_text_input_is_never_matched():
    # `data-qa="text-input"` носит любой текстовый ввод страницы, в том числе
    # поиск в шапке. Письмо, напечатанное в строку поиска, — это письмо,
    # которого работодатель не получил, и мы об этом даже не узнаем.
    for part in SEL_CHAT_MSG.split(","):
        part = part.strip()
        if "text-input" in part:
            assert "chatik-message-input" in part, (
                f"{part!r} цепляет текстовый ввод где угодно на странице")


def test_only_visible_fields_count():
    # У hh в разметке лежат и скрытые заготовки чатов (`chatik-skeleton-chat`),
    # и композер прошлой переписки; невидимое поле принимает fill и молча
    # съедает письмо.
    for part in SEL_CHAT_MSG.split(","):
        assert ":visible" in part, f"{part.strip()!r} без :visible"
