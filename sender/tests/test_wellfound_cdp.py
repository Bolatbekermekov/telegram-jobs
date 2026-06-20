from app.infrastructure.search.wellfound_search import (
    WellfoundSearcher,
    build_chrome_debug_args,
)


def test_chrome_debug_args_carry_port_profile_and_url():
    args = build_chrome_debug_args("C:/prof", 9222, "https://wellfound.com/login")
    assert "--remote-debugging-port=9222" in args
    assert "--user-data-dir=C:/prof" in args
    assert "https://wellfound.com/login" in args


def test_chrome_debug_args_suppress_first_run_so_url_opens():
    # A fresh profile otherwise hijacks the launch with chrome://intro and the
    # target URL never opens; --no-first-run keeps the URL as the active tab.
    args = build_chrome_debug_args("C:/prof", 9222, "https://wellfound.com")
    assert "--no-first-run" in args


def test_searcher_accepts_cdp_url_for_attach_mode():
    s = WellfoundSearcher("state.json", cdp_url="http://127.0.0.1:9222")
    assert s.uses_cdp is True


def test_searcher_defaults_to_launch_mode():
    s = WellfoundSearcher("state.json")
    assert s.uses_cdp is False
