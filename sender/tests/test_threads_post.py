"""Pure assembly of a Threads thread. Fixtures are the real span texts read off the
live page 2026-07-26 — including the interface chrome that has to be stripped."""
from app.domain.threads_post import author_thread_text, post_body

# Root post: badge, relative time, body paragraphs, then engagement counters.
ROOT = ["hiring", "1 дн.",
        "Ищу Full Stack Developer (Lovable / Claude Code / AI-first).",
        "Мы развиваем существующий веб-продукт, который преимущественно создан в "
        "Lovable, и ищем разработчика, который использует AI как основной инструмент.",
        "Что предстоит делать:", "— развивать существующий продукт;",
        "— самостоятельно находить технические решения;",
        "32", "14", "16"]

# Author self-reply: same, plus the "·" separator and the localised author badge.
REPLY_1 = ["hiring", "1 дн.", "·", "Автор",
           "— тестировать изменения и доводить задачи до готового результата.",
           "Что важно:", "— опыт современной Full Stack веб-разработки;",
           "Формат работы:", "— full-time, удалённо;", "1", "1"]

# The self-reply that carries the contact.
REPLY_2 = ["hiring", "1 дн.", "·", "Автор",
           "Для отклика присылайте портфолио в Telegram: @ skyluckwalker", "1"]

FOREIGN = ["1 дн.", "Навайбкодили нейрослоп и ищите инженера чтоб с этим разобраться.",
           "3"]


def test_post_body_drops_badge_and_relative_time():
    body = post_body(ROOT)
    assert body.startswith("Ищу Full Stack Developer")
    assert "hiring" not in body
    assert "1 дн." not in body


def test_post_body_drops_engagement_counters():
    body = post_body(ROOT)
    assert body.endswith("— самостоятельно находить технические решения;")
    for n in ("32", "14", "16"):
        assert not body.endswith(n)


def test_post_body_keeps_every_paragraph():
    """The root body is split across several spans; taking only the longest one
    silently dropped the first two paragraphs."""
    body = post_body(ROOT)
    assert "Ищу Full Stack Developer" in body
    assert "Мы развиваем существующий веб-продукт" in body
    assert "Что предстоит делать:" in body


def test_post_body_drops_the_separator_and_author_badge():
    body = post_body(REPLY_1)
    assert body.startswith("— тестировать изменения")
    assert "Автор" not in body and "·" not in body


def test_post_body_survives_an_english_author_badge():
    """The badge is localised; matching on its text would break on an EN account."""
    parts = ["hiring", "1 d", "·", "Author", "Send your portfolio to @ acme_hr", "1"]
    assert post_body(parts) == "Send your portfolio to @ acme_hr"


def test_post_body_of_only_chrome_is_empty():
    assert post_body(["hiring", "1 дн.", "·", "Автор", "1"]) == ""


def test_post_body_of_nothing_is_empty():
    assert post_body([]) == ""


def test_post_body_keeps_a_counter_shaped_line_inside_the_body():
    """A bare number in the MIDDLE is part of the text; only trailing ones are UI."""
    parts = ["1 дн.", "Бюджет проекта:", "5000", "Пишите в личку сюда", "7"]
    body = post_body(parts)
    assert "5000" in body
    assert not body.endswith("7")


def test_author_thread_text_joins_root_and_self_replies_in_order():
    blocks = [("@lnkrnchk", ROOT), ("@lnkrnchk", REPLY_1), ("@lnkrnchk", REPLY_2),
              ("@so_silly_seal", FOREIGN)]
    text = author_thread_text(blocks, "@lnkrnchk")
    assert text.index("Ищу Full Stack") < text.index("Что важно:")
    assert text.index("Что важно:") < text.index("Для отклика присылайте")


def test_author_thread_text_excludes_other_peoples_replies():
    """Foreign replies carry other candidates' CVs and trolling — they must never
    reach the vacancy text or the cover letter."""
    blocks = [("@lnkrnchk", ROOT), ("@so_silly_seal", FOREIGN)]
    text = author_thread_text(blocks, "@lnkrnchk")
    assert "Навайбкодили" not in text


def test_author_thread_text_matches_the_handle_case_insensitively_and_without_at():
    blocks = [("LnkRnchk", ROOT)]
    assert "Ищу Full Stack" in author_thread_text(blocks, "@lnkrnchk")


def test_the_contact_line_survives_chrome_stripping_verbatim():
    """This module's job ends at handing the contact line through intact. Whether
    `detect_contact` can then read "@ skyluckwalker" depends on the shape the DOM
    reader emits, which is Task 6's problem — see the note below."""
    blocks = [("@lnkrnchk", ROOT), ("@lnkrnchk", REPLY_2)]
    text = author_thread_text(blocks, "@lnkrnchk")
    assert "Для отклика присылайте портфолио в Telegram: @ skyluckwalker" in text


def test_author_thread_text_is_empty_when_the_author_posted_nothing():
    assert author_thread_text([("@someone_else", FOREIGN)], "@lnkrnchk") == ""


def test_a_short_handle_in_its_own_trailing_span_is_not_chrome():
    """8 chars, one word, no punctuation — indistinguishable from a badge by shape
    alone, so it used to be stripped and the contact was lost."""
    assert post_body(["1 дн.", "DM me:", "@acme_hr", "1"]) == "DM me:\n@acme_hr"


def test_a_short_handle_in_a_leading_span_is_not_chrome():
    assert post_body(["hiring", "1 дн.", "@acme_hr", "пишите в личку", "2"]) == (
        "@acme_hr\nпишите в личку")


def test_an_email_in_a_trailing_span_is_not_chrome():
    assert post_body(["1 дн.", "CV:", "hr@acme.com", "3"]) == "CV:\nhr@acme.com"


def test_author_thread_text_matches_a_handle_with_glued_interface_debris():
    """The DOM hands the handle over with a separator or badge stuck to it often
    enough; comparing raw returns "" and the thread silently degrades to the root
    post alone, with no signal that anything was lost."""
    blocks = [("@lnkrnchk·", ROOT), ("lnkrnchk •", REPLY_2)]
    text = author_thread_text(blocks, "@lnkrnchk")
    assert "Ищу Full Stack" in text
    assert "Для отклика присылайте" in text


def test_author_thread_text_does_not_conflate_handles_differing_only_in_dots():
    """Threads handles may contain periods, and an impersonation account differs from
    the real one by exactly that. Normalising the handle's INSIDE away — not just its
    edges — would let a stranger's reply into the vacancy text."""
    blocks = [("@john.doe", ROOT), ("@johndoe", FOREIGN)]
    text = author_thread_text(blocks, "@john.doe")
    assert "Ищу Full Stack" in text
    assert "Навайбкодили" not in text
