"""The text a message really carries, including links that are not in `text`."""
from app.domain.telegram_message import message_text


def test_a_link_hidden_behind_words_is_read_out_of_the_entities():
    """The one shape that broke intake: a forwarded hiring post whose only url
    sits under the words «пост на LinkedIn». `text` alone has no url in it, so
    detect_contact answered None and the bot replied «Не нашёл контакт»."""
    message = {
        "text": "PixelPlex ищет Node.js разработчика. Ищет Мария Кохович, её пост на LinkedIn.",
        "entities": [
            {"type": "bold", "offset": 0, "length": 9},
            {"type": "text_link", "offset": 62, "length": 15,
             "url": "https://www.linkedin.com/posts/maria-kokhovich_hiring-activity-7-abc/"},
        ],
    }

    out = message_text(message)

    assert "https://www.linkedin.com/posts/maria-kokhovich_hiring-activity-7-abc/" in out
    assert out.startswith("PixelPlex ищет Node.js разработчика.")


def test_a_url_already_written_out_is_not_appended_twice():
    """Telegram marks a plain url with a `url` entity too. Appending it again
    would double every link in the summariser's prompt and in «Сырой текст»."""
    message = {
        "text": "Вакансия: https://hh.ru/vacancy/123",
        "entities": [{"type": "url", "offset": 10, "length": 25}],
    }

    assert message_text(message) == "Вакансия: https://hh.ru/vacancy/123"


def test_the_same_hidden_link_twice_is_kept_once():
    message = {
        "text": "тут и тут",
        "entities": [
            {"type": "text_link", "offset": 0, "length": 3, "url": "https://t.me/acme_hr"},
            {"type": "text_link", "offset": 6, "length": 3, "url": "https://t.me/acme_hr"},
        ],
    }

    assert message_text(message).count("https://t.me/acme_hr") == 1


def test_a_photos_caption_and_its_hidden_links_are_read_like_text():
    """A hiring post forwarded WITH its picture has no `text` at all — the words
    and their entities move to `caption` / `caption_entities`."""
    message = {
        "caption": "Ищем бэкендера, пишите сюда.",
        "caption_entities": [
            {"type": "text_link", "offset": 22, "length": 4,
             "url": "https://t.me/acme_hr"},
        ],
    }

    out = message_text(message)

    assert "Ищем бэкендера" in out and "https://t.me/acme_hr" in out


def test_an_ordinary_message_is_returned_as_written():
    assert message_text({"text": "  пиши @ivan_hr  "}) == "пиши @ivan_hr"


def test_a_message_with_nothing_in_it_is_empty():
    assert message_text({}) == ""
    assert message_text({"text": "", "entities": []}) == ""


def test_a_text_mention_without_a_url_is_skipped():
    """`text_mention` carries a user object, not a url. Reading `entity["url"]`
    blindly would put a `None` into the text."""
    message = {
        "text": "пишите Марии",
        "entities": [{"type": "text_mention", "offset": 7, "length": 5,
                      "user": {"id": 1, "first_name": "Мария"}}],
    }

    assert message_text(message) == "пишите Марии"
