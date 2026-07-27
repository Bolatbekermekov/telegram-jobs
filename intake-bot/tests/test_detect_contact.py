from app.domain.contact import (
    Contact, canonical_threads_url, detect_contact, threads_author,
)


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


def test_a_lookalike_host_is_not_a_threads_link():
    """Without a left boundary the pattern matched inside "notthreads.com" and
    canonicalised a threads.com URL that was never sent."""
    assert detect_contact("https://notthreads.com/@lnkrnchk/post/DbL4LxBl6v9") is None


def test_an_uppercase_host_and_a_fragment_are_canonicalised():
    """Both come off real shares: host case carries no meaning, "#" starts a fragment."""
    shouty = "HTTPS://WWW.THREADS.COM/@lnkrnchk/post/DbL4LxBl6v9"
    assert detect_contact(shouty).target == _CLEAN
    assert detect_contact(f"{_CLEAN}#comments").target == _CLEAN


def test_a_threads_profile_without_a_post_is_not_a_lead():
    """A bare profile link holds no vacancy to read; only posts are leads."""
    assert detect_contact("https://www.threads.com/@lnkrnchk") is None


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


def test_a_real_handle_after_the_author_handle_still_wins():
    """The author may be credited before the actual contact is given. Taking only
    the first @handle threw the real recruiter away."""
    c = detect_contact(f"вакансия от @lnkrnchk, пиши @ivan_hr {_CLEAN}")
    assert c == Contact("telegram", "@ivan_hr")


def test_a_real_handle_before_the_author_handle_still_wins():
    c = detect_contact(f"пиши @ivan_hr, вакансия от @lnkrnchk {_CLEAN}")
    assert c == Contact("telegram", "@ivan_hr")


def test_only_the_author_handle_falls_through_to_threads():
    c = detect_contact(f"вакансия от @lnkrnchk смотри {_CLEAN}")
    assert c.platform == "threads"


def test_the_author_handle_repeated_still_falls_through():
    c = detect_contact(f"@lnkrnchk пишет: вакансия от @lnkrnchk {_CLEAN}")
    assert c.platform == "threads"


def test_a_dotted_author_handle_does_not_become_a_truncated_telegram_target():
    """`\\w{4,}` stops at the dot, so "@ivan.hr" used to yield "@ivan" — a real,
    unrelated Telegram user. Threads shares Instagram's dotted namespace."""
    url = "https://www.threads.com/@ivan.hr/post/DbL4LxBl6v9"
    c = detect_contact(f"вакансия от @ivan.hr {url}")
    assert c.platform == "threads"
    assert c.target == url


def test_a_dotted_author_does_not_shadow_a_real_handle():
    url = "https://www.threads.com/@ivan.hr/post/DbL4LxBl6v9"
    c = detect_contact(f"вакансия от @ivan.hr, пиши @ivan_hr {url}")
    assert c == Contact("telegram", "@ivan_hr")


def test_a_short_first_segment_dotted_author_also_falls_through():
    """"@hr.recruiter" passed by accident (`hr` fails \\w{4,}); pin it."""
    url = "https://www.threads.com/@hr.recruiter/post/DbL4LxBl6v9"
    assert detect_contact(f"вакансия от @hr.recruiter {url}").platform == "threads"


def test_a_handle_that_merely_starts_like_the_author_still_wins():
    """The prefix check must not over-match: @lnkrnchk_hr is a DIFFERENT person
    from the author @lnkrnchk, so it is a real Telegram contact."""
    url = "https://www.threads.com/@lnkrnchk/post/DbL4LxBl6v9"
    c = detect_contact(f"пиши @lnkrnchk_hr {url}")
    assert c == Contact("telegram", "@lnkrnchk_hr")


def test_a_dot_glued_to_the_author_handle_does_not_become_a_telegram_target():
    """The whole-token compare alone missed this: "@lnkrnchk.hr" tokenises as
    "lnkrnchk.hr", which != the author, so the truncated "@lnkrnchk" was stored as
    a Telegram target although it was never written as a handle in the message."""
    url = "https://www.threads.com/@lnkrnchk/post/DbL4LxBl6v9"
    assert detect_contact(f"пиши @lnkrnchk.hr {url}").platform == "threads"


def test_a_missing_space_after_a_sentence_dot_does_not_leak_the_author():
    url = "https://www.threads.com/@lnkrnchk/post/DbL4LxBl6v9"
    assert detect_contact(f"вакансия от @lnkrnchk.Пиши в личку {url}").platform == "threads"


def test_a_missing_space_after_a_DOTTED_author_does_not_leak_the_author():
    """The last of the fabricated-target class, and the one the two clauses above
    both missed: for a dotted author the token runs on into the next sentence
    ("ivan.hr.Пиши"), so it equals neither the author nor anything the truncated
    capture can catch — and "@ivan", a real, unrelated Telegram user who is never
    named in the message, was stored as the contact."""
    url = "https://www.threads.com/@ivan.hr/post/DbL4LxBl6v9"
    assert detect_contact(f"вакансия от @ivan.hr.Пиши в личку {url}").platform == "threads"


def test_the_author_dot_clause_does_not_swallow_a_different_person():
    """The exemption is `author + "."`, never a bare prefix: "@lnkrnchk_hr" is a
    different person from the author "@lnkrnchk" and must still win as a real
    Telegram contact. Pinned next to the case above because widening one to fix
    the other is exactly the mistake."""
    url = "https://www.threads.com/@lnkrnchk/post/DbL4LxBl6v9"
    assert detect_contact(f"пиши @lnkrnchk_hr {url}") == Contact("telegram", "@lnkrnchk_hr")


def test_email_in_the_message_still_beats_a_threads_link():
    c = detect_contact(f"{_CLEAN} резюме на hr@acme.com")
    assert c.platform == "email"


def test_threads_helpers():
    assert canonical_threads_url(_SHARED) == _CLEAN
    assert threads_author(_SHARED) == "@lnkrnchk"
    assert threads_author("https://hh.ru/vacancy/1") == ""


# --- Golden parity vectors ---------------------------------------------------
# This table is checked into BOTH suites — sender/tests/test_contact.py and
# intake-bot/tests/test_detect_contact.py — with identical data, deliberately
# duplicated. The two apps are separate deploys that never import each other, so the
# only thing that catches a drift in one of the two `contact.py` copies is each suite
# pinning the answers itself. Change one copy of this table, change the other.
#
# It exists because the sender copy diverged behaviourally from the intake original on
# the day it was created: a handle rule widened to `@\s?` also matched the "at" of
# "hr @ acme.com" and "Role @ Company" and returned a fabricated "@acme" target,
# pre-empting the email, linkedin and hh rules that held the real contact. A
# hand-written parity check missed it because its inputs contained no "X @ domain.tld"
# and no prose "@". The last four rows are that shape.
#
# Threads URLs are deliberately kept out: a Threads link legitimately changes the
# answer between the apps (intake has a `threads` rule and an author exemption, the
# sender has neither by design), so no single expectation could hold for both. Threads
# behaviour is pinned per-app instead, outside this table.
_GOLDEN = [
    # (text, expected platform, expected target) — a None platform means no contact.
    ("Контакт: https://t.me/ivanhr спасибо", "telegram", "https://t.me/ivanhr"),
    ("Ищем backend. Пиши @ivan_hr по вакансии", "telegram", "@ivan_hr"),
    ("резюме на hr@acme.com", "email", "hr@acme.com"),
    # _EMAIL_RE's tail class `[\w.-]+` eats the period that ended the sentence, so
    # without `_clean` the target is "hr@acme.io." — which most MTAs reject at
    # RCPT TO, landing the lead `failed` with the recruiter never contacted. Newly
    # load-bearing: Threads prose is the first free text detect_contact reads, and
    # prose ends its sentences with periods.
    ("резюме на hr@acme.io.", "email", "hr@acme.io"),
    # The (?:^|\s) anchor: the "@" inside a well-formed email is not a handle.
    ("john@gmail.com", "email", "john@gmail.com"),
    # Ordering: the handle rule is second of six, so a later handle beats an earlier email.
    ("пиши boss@acme.com или @ivan_hr", "telegram", "@ivan_hr"),
    ("профиль https://linkedin.com/in/ivan", "linkedin", "https://linkedin.com/in/ivan"),
    ("см. (linkedin.com/in/abc).", "linkedin", "linkedin.com/in/abc"),
    # Regional domain folded onto hh.ru (the saved session is hh.ru-only), tracking dropped.
    ("откликнуться https://astana.hh.kz/vacancy/135297431?from=share_ios",
     "hh", "https://hh.ru/vacancy/135297431"),
    # The vacancy wins over the app-download footer in the same share.
    ("Вакансия: https://hh.kz/vacancy/135297431 Отправлено из мобильного приложения hh"
     " https://hh.ru/mobile", "hh", "https://hh.ru/vacancy/135297431"),
    ("https://wellfound.com/jobs/1-dev", "wellfound", "https://wellfound.com/jobs/1-dev"),
    ("просто описание вакансии", None, None),
    # "@" as the word "at", and space-obfuscated emails. A widened handle rule turns
    # every one of these into a fabricated Telegram target, and in three of the four
    # the real contact is sitting later in the same text.
    ("Резюме отправляйте: hr @ acme.com", None, None),
    ("пишите hr @ acme.com или в телеграм @ivan_hr", "telegram", "@ivan_hr"),
    ("Ищем разработчика @ Astana, откликайтесь на hh.ru/vacancy/12345",
     "hh", "https://hh.ru/vacancy/12345"),
    ("CV -> hr @ acme.com или https://linkedin.com/in/ivan",
     "linkedin", "https://linkedin.com/in/ivan"),
]


def test_golden_parity_vectors():
    """Every rule, and the ordering between them, pinned as data. Reports every
    drifted vector at once rather than stopping at the first."""
    drift = []
    for text, platform, target in _GOLDEN:
        expected = None if platform is None else (platform, target)
        c = detect_contact(text)
        actual = None if c is None else (c.platform, c.target)
        if actual != expected:
            drift.append(f"  {text!r}\n    expected {expected}\n    got      {actual}")
    assert not drift, "detect_contact drifted from the golden vectors:\n" + "\n".join(drift)
