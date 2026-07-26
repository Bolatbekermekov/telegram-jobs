from app.domain.contact import Contact, detect_contact


def test_telegram_handle():
    c = detect_contact("Ищем backend. Пиши @ivan_hr по вакансии")
    assert c == Contact("telegram", "@ivan_hr")


def test_telegram_tme_link():
    c = detect_contact("Контакт: https://t.me/ivanhr спасибо")
    assert c.platform == "telegram"
    assert "t.me/ivanhr" in c.target


def test_email():
    c = detect_contact("Резюме на recruiter@company.com")
    assert c == Contact("email", "recruiter@company.com")


def test_plain_email_is_not_telegram():
    c = detect_contact("john@gmail.com")
    assert c.platform == "email"
    assert c.target == "john@gmail.com"


def test_linkedin():
    c = detect_contact("Профиль: linkedin.com/in/ivan-ivanov апплай тут")
    assert c.platform == "linkedin"
    assert "linkedin.com/in/ivan-ivanov" in c.target


def test_hh():
    c = detect_contact("Откликнуться: https://hh.ru/vacancy/12345?from=x")
    assert c.platform == "hh"
    assert "hh.ru/vacancy/12345" in c.target


def test_wellfound():
    c = detect_contact("Apply at https://wellfound.com/jobs/987-backend-engineer")
    assert c.platform == "wellfound"
    assert "wellfound.com/jobs/987-backend-engineer" in c.target


def test_priority_telegram_over_email():
    c = detect_contact("Пиши @ivan_hr или на boss@company.com")
    assert c.platform == "telegram"


def test_priority_email_over_linkedin():
    c = detect_contact("mail me@x.com or linkedin.com/in/me")
    assert c.platform == "email"


def test_none_when_no_contact():
    assert detect_contact("Просто описание вакансии без контактов") is None


def test_strips_trailing_punctuation_from_url():
    c = detect_contact("см. (linkedin.com/in/abc).")
    assert c.target.endswith("abc")


def test_ios_share_picks_the_vacancy_not_the_app_footer():
    """The hh iOS share sheet appends its own download link; a rule that took any
    hh URL stored that footer as the target and lost the vacancy (12 real leads)."""
    text = ("Vacancy: https://hh.kz/vacancy/135297431?from=share_ios\n\n"
            "Sent via hh mobile app https://hh.ru/mobile?from=share_ios")
    c = detect_contact(text)
    assert c.platform == "hh"
    assert "/vacancy/135297431" in c.target      # the vacancy, not the app footer
    assert "mobile" not in c.target


def test_regional_hh_domains_are_recognised():
    for host in ("hh.kz", "hh.uz", "hh.by", "astana.hh.kz"):
        c = detect_contact(f"вакансия https://{host}/vacancy/123")
        assert c is not None and c.platform == "hh", host


def test_plain_hh_link_without_a_vacancy_path_still_works():
    c = detect_contact("смотри https://hh.ru/employer/123")
    assert c.platform == "hh"
    assert c.target == "https://hh.ru/employer/123"


# --- canonical hh links stored in the sheet ---------------------------------

def test_ios_share_is_stored_as_a_plain_desktop_link():
    """What the phone sends vs what the sheet should hold."""
    text = ("Vacancy: https://hh.kz/vacancy/135297431?from=share_ios\n\n"
            "Sent via hh mobile app https://hh.ru/mobile?from=share_ios")
    assert detect_contact(text).target == "https://hh.ru/vacancy/135297431"


def test_regional_subdomain_is_folded_onto_hh_ru():
    c = detect_contact("https://astana.hh.kz/vacancy/135297431?from=share_ios&query=qa")
    assert c.target == "https://hh.ru/vacancy/135297431"


def test_search_tracking_is_dropped():
    c = detect_contact("https://hh.ru/vacancy/133978075?query=junior&hhtmFrom=vacancy_search_list")
    assert c.target == "https://hh.ru/vacancy/133978075"


def test_an_already_clean_link_is_unchanged():
    c = detect_contact("https://hh.ru/vacancy/135297431")
    assert c.target == "https://hh.ru/vacancy/135297431"


def test_non_vacancy_regional_link_keeps_its_path():
    """Only the host is rebased when there is no vacancy id to canonicalise."""
    c = detect_contact("https://hh.kz/employer/12345")
    assert c.target == "https://hh.ru/employer/12345"


def test_other_platforms_are_not_touched():
    assert detect_contact("https://www.linkedin.com/in/x?trk=abc").platform == "linkedin"
    assert detect_contact("@nick").target == "@nick"


# --- Threads --------------------------------------------------------------

from app.domain.contact import (  # noqa: E402
    canonical_threads_url, threads_author, threads_post_id,
)

_SHARED = ("https://www.threads.com/@lnkrnchk/post/DbL4LxBl6v9"
           "?xmt=AQG0bheD9uqmoSjOr9bFyIfWrZmjZK8OWTtZ0RjfvAVPAHs981VOMdhda3xuSsAZwsdDgJA"
           "&slof=1")
_CLEAN = "https://www.threads.com/@lnkrnchk/post/DbL4LxBl6v9"


def test_threads_post_is_detected():
    c = detect_contact(_CLEAN)
    assert c == Contact("threads", _CLEAN)


def test_threads_share_tracking_is_dropped():
    """The share sheet appends ?xmt=…&slof=1; the sheet must hold a plain URL."""
    assert detect_contact(_SHARED).target == _CLEAN


def test_threads_net_is_folded_onto_threads_com():
    c = detect_contact("вакансия https://www.threads.net/@lnkrnchk/post/DbL4LxBl6v9")
    assert c.target == _CLEAN


def test_threads_without_scheme_or_www():
    assert detect_contact("threads.com/@lnkrnchk/post/DbL4LxBl6v9").target == _CLEAN


def test_threads_url_author_is_not_read_as_a_telegram_handle():
    """The '@' in the URL path is preceded by '/', so _HANDLE_RE must not fire."""
    assert detect_contact(_CLEAN).platform == "threads"


def test_a_real_telegram_handle_still_beats_a_threads_link():
    c = detect_contact(f"Пиши @ivan_hr по вакансии {_CLEAN}")
    assert c == Contact("telegram", "@ivan_hr")


def test_the_threads_authors_own_handle_does_not_hijack_the_lead():
    """"вакансия от @lnkrnchk <ссылка>" must stay threads: that handle is the post
    author, not a Telegram user, and DMing it would reach nobody."""
    c = detect_contact(f"вакансия от @lnkrnchk {_CLEAN}")
    assert c.platform == "threads"


def test_email_in_the_message_still_beats_a_threads_link():
    c = detect_contact(f"{_CLEAN} резюме на hr@acme.com")
    assert c.platform == "email"


def test_threads_helpers():
    assert canonical_threads_url(_SHARED) == _CLEAN
    assert threads_post_id(_SHARED) == "DbL4LxBl6v9"
    assert threads_author(_SHARED) == "@lnkrnchk"
    assert threads_author("https://hh.ru/vacancy/1") == ""
