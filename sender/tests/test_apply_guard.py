"""Guards that stand between an injected page and an irreversible submit.

These don't test that injections are detected — they can't be. They test that a
successful injection still can't reach a submit on an unknown host, and can't
carry the candidate's contact details out through a free-text answer.
"""
from app.application.apply_guard import ALLOWED_APPLY_HOSTS, host_allowed, leaked_secrets
from app.domain.apply_profile import ApplyProfile


def _profile(**kw):
    return ApplyProfile(
        email="bolatbek@example.com",
        phone="+7 (700) 123-45-67",
        linkedin="linkedin.com/in/bolatbek",
        **kw,
    )


# --- host allowlist ---------------------------------------------------------

def test_known_ats_host_is_allowed():
    assert host_allowed("https://boards.greenhouse.io/acme/jobs/123")


def test_unknown_host_is_rejected():
    assert not host_allowed("https://careers.random-startup.xyz/apply")


def test_subdomain_of_an_allowed_vendor_is_allowed():
    """Workday shards per customer and region; listing every host is impossible."""
    assert host_allowed("https://acme.wd5.myworkdayjobs.com/en-US/careers/job/1")


def test_lookalike_domain_is_rejected():
    """greenhouse.io.evil.tld must not pass as greenhouse.io."""
    assert not host_allowed("https://boards.greenhouse.io.evil.tld/apply")


def test_allowed_host_as_a_path_segment_is_rejected():
    assert not host_allowed("https://evil.tld/boards.greenhouse.io/apply")


def test_garbage_url_is_rejected():
    for url in ("", "not-a-url", "https://", "mailto:hr@acme.com"):
        assert not host_allowed(url), url


def test_host_matching_ignores_case_and_trailing_dot():
    assert host_allowed("https://Jobs.Lever.CO/acme/1")
    assert host_allowed("https://jobs.lever.co./acme/1")


def test_the_platforms_we_apply_on_are_allowed():
    """hh/wellfound/linkedin route through this driver too — don't lock them out."""
    for host in ("hh.ru", "wellfound.com", "linkedin.com"):
        assert host in ALLOWED_APPLY_HOSTS


# --- contact-detail leak ----------------------------------------------------

def test_a_normal_answer_leaks_nothing():
    text = "Мне интересна разработка на .NET, есть коммерческий опыт с C# и SQL."
    assert leaked_secrets(text, _profile()) == []


def test_email_in_a_free_text_answer_is_caught():
    assert "email" in leaked_secrets(
        "Свяжитесь со мной: bolatbek@example.com", _profile())


def test_phone_is_caught_despite_different_formatting():
    """The page asked for a phone; the model reformatted it. Still a leak."""
    assert "phone" in leaked_secrets("Мой номер 77001234567", _profile())


def test_phone_is_caught_when_written_with_separators():
    assert "phone" in leaked_secrets("тел. +7 700 123 45 67", _profile())


def test_linkedin_url_in_an_answer_is_caught():
    assert "linkedin" in leaked_secrets(
        "Профиль: linkedin.com/in/bolatbek", _profile())


def test_several_leaks_are_all_reported():
    text = "bolatbek@example.com, 77001234567"
    assert set(leaked_secrets(text, _profile())) == {"email", "phone"}


def test_an_empty_profile_field_never_matches():
    """A blank email must not make every answer look like a leak."""
    blank = ApplyProfile(email="", phone="", linkedin="")
    assert leaked_secrets("любой текст с @ и цифрами 12345678", blank) == []


def test_a_short_phone_is_not_matched():
    """Too few digits to be a real number — matching it would fire on any date."""
    short = ApplyProfile(email="", phone="12345", linkedin="")
    assert leaked_secrets("код 12345 и ещё 999", short) == []


def test_unrelated_digits_do_not_count_as_a_phone():
    assert leaked_secrets("Опыт: 5 лет, 2019-2024, зарплата 300000", _profile()) == []


def test_empty_text_leaks_nothing():
    assert leaked_secrets("", _profile()) == []


# --- routes seen live on 2026-07-20 (make apply_probe) ----------------------

def test_ats_vendor_behind_a_company_page_is_allowed():
    """superplay.co routes IFRAME_ATS into comeet.co — the form is the vendor's,
    so the check runs on the vendor host, which must pass."""
    assert host_allowed("https://www.comeet.co/jobs/superplay/28/26/apply")


def test_company_own_page_is_still_rejected():
    """ddrive.tech-style page: if it ever served a plain form we'd fill it blind."""
    assert not host_allowed("https://www.ddrive.tech/team/junior-software-developer")


def test_join_com_is_allowed():
    """join.com hosts the apply flow itself (live probe case 1)."""
    assert host_allowed("https://join.com/companies/lemvos/16426802-internship")
