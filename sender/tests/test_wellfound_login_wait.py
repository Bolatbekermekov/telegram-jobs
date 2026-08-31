"""Вход в Wellfound ждут опросом, а не по Enter.

`input()` в этой команде падал с EOFError: её запускают из оболочки без stdin
(живьём 2026-08-29). Окно Chrome к тому моменту уже открыто, то есть падение
отнимало не удобство, а весь смысл команды — человек не успевал залогиниться.
"""
from app.interface.cli import _await_wellfound_login
from app.infrastructure.search.wellfound_search import login_state


def test_cloudflare_page_is_not_mistaken_for_a_session():
    assert login_state("https://wellfound.com/login", "Один момент…") == "cloudflare"
    assert login_state("https://wellfound.com/login", "Just a moment...") == "cloudflare"


def test_login_form_is_not_mistaken_for_a_session():
    assert login_state("https://wellfound.com/login", "Log In - Wellfound") == "login"


def test_a_loaded_feed_reads_as_ready():
    assert login_state("https://wellfound.com/jobs", "Jobs - Wellfound") == "ready"


def test_blank_tab_is_not_ready():
    """about:blank — вкладка ещё не доехала, а не «вошли»."""
    assert login_state("about:blank", "") == "cloudflare"


def _states(*seq):
    it = iter(seq)
    return lambda: next(it, ("ready", ""))


def test_waits_through_cloudflare_and_the_login_form():
    slept = []
    assert _await_wellfound_login(
        wait_seconds=60, poll_seconds=1,
        read_state=_states(("cloudflare", ""), ("login", ""), ("ready", "")),
        sleep=slept.append) is True
    assert slept == [1, 1]          # два ожидания, потом успех


def test_gives_up_after_the_deadline_without_hanging():
    slept = []
    assert _await_wellfound_login(
        wait_seconds=9, poll_seconds=3,
        read_state=lambda: ("login", ""),
        sleep=slept.append) is False
    assert len(slept) == 3          # ровно три опроса, потом отказ


def test_unreachable_chrome_is_reported_not_swallowed(capsys):
    _await_wellfound_login(wait_seconds=3, poll_seconds=3,
                           read_state=lambda: ("unreachable", "ECONNREFUSED 9222"),
                           sleep=lambda s: None)
    assert "ECONNREFUSED 9222" in capsys.readouterr().out
