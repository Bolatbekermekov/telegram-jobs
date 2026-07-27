"""The model as a FALLBACK contact detector: prompt building and answer vetting.

Rules decide first (`detect_contact`); this runs only when they found nothing. So
every test here is about one thing: what the model returns is *evidence*, not a
decision. `parse_contact_response` is the gate, and each of its five checks gets
its own test, deliberately isolated so that a test proves the check it names and
not a neighbour.

Nothing here touches the network.
"""
from app.application.contact_llm import build_contact_prompt, parse_contact_response

_AUTHOR = "@lnkrnchk"

# The live post that motivated the fallback: the author typed a space after the
# at-sign, so no regex takes it (see the reverted `@\s+` experiment in contact.py).
_SPACED = ("Ищу Full Stack Developer (Lovable / Claude Code / AI-first).\n\n"
           "Для отклика присылайте портфолио в Telegram: @ skyluckwalker")


# --- the prompt -----------------------------------------------------------

def test_prompt_carries_the_thread_and_asks_for_strict_json():
    system, user = build_contact_prompt(_SPACED)
    assert "@ skyluckwalker" in user
    assert "JSON" in system


def test_prompt_forbids_inventing_a_contact():
    """The first line of defence: told to answer nothing rather than guess."""
    system, _ = build_contact_prompt(_SPACED)
    assert '"platform": null' in system
    assert "не выдумывай" in system.lower()


# --- the happy paths ------------------------------------------------------

def test_a_handle_the_rules_missed_is_recovered():
    got = parse_contact_response(
        '{"platform": "telegram", "target": "@skyluckwalker"}', _SPACED, _AUTHOR)
    assert got is not None
    assert (got.platform, got.target) == ("telegram", "@skyluckwalker")


def test_a_handle_without_the_at_sign_is_normalised():
    got = parse_contact_response(
        '{"platform": "telegram", "target": "skyluckwalker"}', _SPACED, _AUTHOR)
    assert got.target == "@skyluckwalker"


def test_json_wrapped_in_prose_is_still_read():
    raw = 'Вот результат:\n```json\n{"platform": "telegram", "target": "@skyluckwalker"}\n```'
    assert parse_contact_response(raw, _SPACED, _AUTHOR).target == "@skyluckwalker"


def test_an_email_is_recovered():
    src = "Ищем разработчика. Резюме на hr@acme.io"
    got = parse_contact_response('{"platform": "email", "target": "hr@acme.io"}',
                                 src, _AUTHOR)
    assert (got.platform, got.target) == ("email", "hr@acme.io")


def test_a_regional_hh_link_is_canonicalised_like_the_rules_do():
    """Same treatment as detect_contact: the saved hh session is hh.ru-only."""
    src = "Откликнуться можно на hh.kz/vacancy/135297431"
    got = parse_contact_response(
        '{"platform": "hh", "target": "https://hh.kz/vacancy/135297431"}', src, _AUTHOR)
    assert got.target == "https://hh.ru/vacancy/135297431"


# --- check 1: it must be JSON ---------------------------------------------

def test_prose_instead_of_json_is_dropped():
    assert parse_contact_response("Контакт: пишите @skyluckwalker в телеграм",
                                  _SPACED, _AUTHOR) is None


def test_an_empty_answer_is_dropped():
    assert parse_contact_response("", _SPACED, _AUTHOR) is None


def test_a_null_platform_means_no_contact():
    assert parse_contact_response('{"platform": null}', _SPACED, _AUTHOR) is None


def test_a_missing_target_is_dropped():
    assert parse_contact_response('{"platform": "telegram"}', _SPACED, _AUTHOR) is None


# --- check 2: the platform must be one build_channel can serve -------------

def test_an_unknown_platform_is_dropped():
    """`whatsapp` would reach build_channel and blow up the whole run."""
    src = "Ищем разработчика. WhatsApp +79990000000"
    assert parse_contact_response(
        '{"platform": "whatsapp", "target": "+79990000000"}', src, _AUTHOR) is None


def test_the_threads_platform_is_not_accepted_from_the_model():
    """`threads` is the fallback the resolver picks itself, never a "found" contact."""
    src = "Ищем разработчика. Пишите @ hiringteam"
    assert parse_contact_response(
        '{"platform": "threads", "target": "@hiringteam"}', src, _AUTHOR) is None


# --- check 3: the target must have the right shape for its platform --------

def test_a_telegram_target_that_is_not_a_handle_is_dropped():
    """Everything else passes here, so this test can only fail on the shape check."""
    src = "Ищем разработчика. По всем вопросам пиши в тг"
    assert parse_contact_response(
        '{"platform": "telegram", "target": "пиши в тг"}', src, _AUTHOR) is None


def test_a_too_short_telegram_handle_is_dropped():
    src = "Ищем разработчика. Пишите @ hr"
    assert parse_contact_response('{"platform": "telegram", "target": "@hr"}',
                                  src, _AUTHOR) is None


def test_a_malformed_email_is_dropped():
    src = "Ищем разработчика. Пишите на hr@company"
    assert parse_contact_response('{"platform": "email", "target": "hr@company"}',
                                  src, _AUTHOR) is None


def test_a_url_on_the_wrong_host_is_dropped():
    """The URL is right there in the thread, so only the host check rejects it."""
    src = "Ищем разработчика. Анкета: https://evil.com/in/hr-acme"
    assert parse_contact_response(
        '{"platform": "linkedin", "target": "https://evil.com/in/hr-acme"}',
        src, _AUTHOR) is None


# --- check 4: the target must occur in the thread (anti-invention) ---------

def test_a_target_absent_from_the_thread_is_dropped():
    """The load-bearing guard: a well-formed handle that nobody wrote is a
    hallucination, and sending to it means messaging a stranger."""
    src = "Ищем разработчика. Пишите @ skyluckwalker"
    assert parse_contact_response(
        '{"platform": "telegram", "target": "@hr_invented"}', src, _AUTHOR) is None


def test_an_invented_email_is_dropped_even_with_a_plausible_domain():
    src = "Ищем разработчика в Acme. Сайт acme.io"
    assert parse_contact_response('{"platform": "email", "target": "hr@acme.io"}',
                                  src, _AUTHOR) is None


def test_the_occurrence_check_ignores_case_at_signs_and_spaces():
    src = "Для отклика — TELEGRAM: @ Sky Luck Walker"
    got = parse_contact_response(
        '{"platform": "telegram", "target": "@skyluckwalker"}', src, _AUTHOR)
    assert got is not None and got.target == "@skyluckwalker"


def test_a_url_without_the_scheme_in_the_thread_still_matches():
    src = "Вакансия: hh.ru/vacancy/135297431"
    got = parse_contact_response(
        '{"platform": "hh", "target": "https://hh.ru/vacancy/135297431"}', src, _AUTHOR)
    assert got is not None


# --- check 5: the author's Threads handle is not a Telegram username -------

def test_the_authors_own_handle_is_dropped():
    """@lnkrnchk on Threads and @lnkrnchk on Telegram are different people."""
    src = "Ищем разработчика. Пишите мне @ lnkrnchk, отвечаю быстро."
    assert parse_contact_response('{"platform": "telegram", "target": "@lnkrnchk"}',
                                  src, _AUTHOR) is None


def test_the_author_check_ignores_case_and_the_at_sign():
    src = "Ищем разработчика. Пишите мне @ LNKRNCHK"
    assert parse_contact_response('{"platform": "telegram", "target": "LNKRNCHK"}',
                                  src, "lnkrnchk") is None


def test_the_author_check_does_not_touch_other_platforms():
    """Only Telegram confuses the two namespaces; an email is an email."""
    src = "Ищем разработчика. Почта lnkrnchk@acme.io"
    got = parse_contact_response('{"platform": "email", "target": "lnkrnchk@acme.io"}',
                                 src, _AUTHOR)
    assert got is not None and got.platform == "email"


def test_an_unknown_author_does_not_block_a_valid_handle():
    got = parse_contact_response(
        '{"platform": "telegram", "target": "@skyluckwalker"}', _SPACED, "")
    assert got is not None
