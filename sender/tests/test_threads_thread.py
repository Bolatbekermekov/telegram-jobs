"""The DOM reader is thin, so these tests fake the page object — the same pattern
used by test_linkedin_channel.py and test_headhunter_channel.py."""
import pytest

from app.domain.contact import detect_contact
from app.infrastructure.threads_thread import (
    author_from_url, read_thread_blocks, render_thread, resolve_thread,
)

_URL = "https://www.threads.com/@lnkrnchk/post/DbL4LxBl6v9"

_BLOCKS = [
    ["@lnkrnchk", ["hiring", "1 дн.", "Ищу Full Stack Developer.", "32"]],
    ["@lnkrnchk", ["hiring", "1 дн.", "·", "Автор", "Что важно: опыт с Lovable.", "1"]],
    ["@lnkrnchk", ["hiring", "1 дн.", "·", "Автор",
                   "Для отклика присылайте портфолио в Telegram: @ skyluckwalker", "1"]],
    ["@troll", ["1 дн.", "Навайбкодили нейрослоп.", "3"]],
]


class FakePage:
    """Mimics the bits of a Playwright page that the reader touches."""

    def __init__(self, blocks=None, goto_error=None, eval_error=None):
        self._blocks = blocks if blocks is not None else _BLOCKS
        self._goto_error = goto_error
        self._eval_error = eval_error
        self.goto_calls = []

    def goto(self, url, **kwargs):
        self.goto_calls.append(url)
        if self._goto_error:
            raise self._goto_error

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, script):
        if self._eval_error:
            raise self._eval_error
        return self._blocks


def test_author_from_url():
    assert author_from_url(_URL) == "@lnkrnchk"
    assert author_from_url("https://www.threads.net/@a.b/post/X1") == "@a.b"
    assert author_from_url("https://hh.ru/vacancy/1") == ""
    assert author_from_url("") == ""


def test_read_thread_blocks_normalises_to_tuples():
    blocks = read_thread_blocks(FakePage())
    assert blocks[0] == ("@lnkrnchk", ["hiring", "1 дн.", "Ищу Full Stack Developer.", "32"])
    assert len(blocks) == 4


def test_read_thread_blocks_tolerates_junk_rows():
    page = FakePage(blocks=[["@a", ["text long enough"]], None, ["@b"], "nonsense",
                            ["@c", "not-a-list"]])
    assert read_thread_blocks(page) == [("@a", ["text long enough"])]


def test_resolve_thread_returns_only_the_authors_posts():
    text = resolve_thread(FakePage(), _URL)
    assert "Ищу Full Stack Developer." in text
    assert "Что важно: опыт с Lovable." in text
    assert "@ skyluckwalker" in text
    assert "Навайбкодили" not in text


def test_resolve_thread_keeps_thread_order():
    text = resolve_thread(FakePage(), _URL)
    assert text.index("Ищу Full Stack") < text.index("Что важно") < text.index("Для отклика")


def test_resolve_thread_navigates_to_the_url():
    page = FakePage()
    resolve_thread(page, _URL)
    assert page.goto_calls == [_URL]


def test_resolve_thread_returns_empty_when_navigation_fails():
    """A login wall, a timeout or a network blip must not raise: the caller falls
    back to the 480 chars the intake already stored."""
    assert resolve_thread(FakePage(goto_error=RuntimeError("timeout")), _URL) == ""


def test_resolve_thread_returns_empty_when_the_dom_read_fails():
    assert resolve_thread(FakePage(eval_error=RuntimeError("detached")), _URL) == ""


def test_resolve_thread_returns_empty_when_the_page_has_no_posts():
    assert resolve_thread(FakePage(blocks=[]), _URL) == ""


def test_resolve_thread_returns_empty_for_a_non_threads_url():
    assert resolve_thread(FakePage(), "https://hh.ru/vacancy/1") == ""


def test_resolve_thread_does_not_open_a_page_for_a_non_threads_url():
    """The URL check comes first: a non-Threads lead must not cost a page load."""
    page = FakePage()
    resolve_thread(page, "https://hh.ru/vacancy/1")
    assert page.goto_calls == []


# --- the contact, which is the whole point of reading the thread ----------------
#
# Measured live 2026-07-26 (see task-6-report.md). Threads renders a real mention
# as `a[href^="/@"]` wrapped in block-level <div>s, so plain innerText returns
# "…Telegram: \n@nick\n" and breaks the sentence. The reader unwraps that anchor,
# so the handle reaches this text glued to its own at-sign.

def test_detect_contact_finds_a_glued_mention_in_the_assembled_thread_text():
    page = FakePage(blocks=[
        ["@lnkrnchk", ["hiring", "1 дн.", "Ищу Full Stack Developer.", "32"]],
        ["@lnkrnchk", ["hiring", "1 дн.", "·", "Автор",
                       "Для отклика присылайте портфолио в Telegram: @skyluckwalker", "1"]],
    ])
    contact = detect_contact(resolve_thread(page, _URL))
    assert contact is not None
    assert contact.platform == "telegram"
    assert contact.target == "@skyluckwalker"


def test_an_at_sign_the_author_typed_with_a_space_stays_undetectable():
    """Documents an OPEN decision, not a desired outcome.

    On the live post the author typed «в Telegram: @ skyluckwalker» — with the
    space — and Threads stored it that way (its own payload carries
    "Telegram: \\u0040 skyluckwalker" with linkified_in_app_url: null, because the
    space stops it being a mention). So this is not a rendering artifact the DOM
    reader can undo: the DOM reproduces the author's text faithfully.

    Closing it needs a text-level rule, and the obvious one — a blanket
    `@\\s+` -> `@` — is the change that was reverted from detect_contact, because
    it turns "hr @ acme.com" into "@acme" and "Role @ Astana" into "@Astana".
    Left undetected on purpose pending a human decision; see task-6-report.md.
    """
    text = resolve_thread(FakePage(), _URL)
    assert "@ skyluckwalker" in text
    assert detect_contact(text) is None


# --- selector drift canary -----------------------------------------------------
#
# Meta ships DOM changes without notice, so the JS is pinned against the real page.
# Deselected by `make test-unit`; run with `sender/.venv/bin/python -m pytest
# sender/tests/test_threads_thread.py -m live`.

@pytest.mark.live
def test_live_render_thread_reads_the_whole_authors_thread():
    text = render_thread(_URL)
    # the root post and BOTH self-replies, none of which og:description carries
    assert "Ищу Full Stack Developer" in text
    assert "Что важно:" in text
    assert "Для отклика присылайте портфолио в Telegram:" in text
    # foreign replies stay out: trolling and other candidates' CVs
    assert "Навайбкодили" not in text
    assert "резюме" not in text
    # the bullet lists keep the line breaks that separate their items
    assert "\n— развивать существующий продукт;" in text


@pytest.mark.live
def test_live_render_thread_emits_no_interface_chrome():
    text = render_thread(_URL)
    # the in-body translate control, which sits INSIDE the body span and so used
    # to arrive glued to the last line of the vacancy
    assert "Translate" not in text
    assert "Показать перевод" not in text
    # engagement counters, including the abbreviated forms that shape cannot catch
    for junk in ("тыс.", "views", "просмотр"):
        assert junk not in text
    # the author handle span, which would shield the badge row into the body
    assert "lnkrnchk" not in text
    assert "Автор" not in text and "Author" not in text


@pytest.mark.live
def test_live_render_thread_returns_empty_for_a_dead_post():
    """A deleted or private post must degrade to "", not raise."""
    assert render_thread("https://www.threads.com/@lnkrnchk/post/ZZZZnotapost") == ""
