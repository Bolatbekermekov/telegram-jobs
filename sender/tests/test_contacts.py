"""Один телеграм-ник и один LinkedIn на все площадки.

Контакты лежали в трёх местах — signature.txt, apply_profile.yml и CV, которое
читает модель, — и разошлись. Работодателю уходил ник, по которому не отвечают:
в подписи один, в форме отклика второй, в тексте письма третий. Здесь
проверяется, что источник правды один (подпись) и что к нему приводится всё
исходящее: тело письма, записка, поля формы и ответы модели.
"""
from app.application.generate_message import GenerateMessage
from app.application.hh_questions import canonicalize_answers
from app.domain.apply_profile import ApplyProfile
from app.domain.contacts import (
    Contacts, canonicalize, normalize_handle, normalize_linkedin, parse_contacts,
)
from app.domain.lead import Lead
from app.infrastructure.apply_profile_loader import load_apply_profile

SIGN = ("С уважением, Bolatbek\n"
        "Telegram: @bolatbek_yermekov\n"
        "Email: ermekovbolatbek50@gmail.com\n"
        "LinkedIn: https://www.linkedin.com/in/bolatbek-yermekov-9b2261418/")
CONTACTS = parse_contacts(SIGN)


def _lead(text="Ищем Backend разработчика"):
    return Lead(row=2, lead_id="1", platform="telegram", target="@hr",
                vacancy_context=text, raw_text=text, status="new")


# --- разбор подписи ---------------------------------------------------------

def test_contacts_come_from_the_signature_block():
    assert CONTACTS.telegram == "@bolatbek_yermekov"
    assert CONTACTS.linkedin == "https://www.linkedin.com/in/bolatbek-yermekov-9b2261418/"


def test_a_signature_without_contact_lines_gives_nothing_to_enforce():
    """Пустой канон отключает подмену: стирать чужой ник не за что."""
    assert parse_contacts("С уважением, Иван") == Contacts()
    assert not parse_contacts("")


def test_a_handle_is_read_in_any_notation():
    for written in ("@bolatbek_yermekov", "bolatbek_yermekov",
                    "t.me/bolatbek_yermekov", "https://t.me/bolatbek_yermekov"):
        assert normalize_handle(written) == "@bolatbek_yermekov"


def test_a_linkedin_line_without_protocol_still_becomes_a_link():
    assert normalize_linkedin("www.linkedin.com/in/someone/") == \
        "https://www.linkedin.com/in/someone/"


# --- подмена в тексте -------------------------------------------------------

def test_any_other_handle_in_the_text_becomes_ours():
    got = canonicalize("Telegram: @bolatbekermeko_v", CONTACTS)
    assert got == "Telegram: @bolatbek_yermekov"


def test_a_link_stays_a_link_and_a_handle_stays_a_handle():
    """Форма записи чужая, ник наш: подпись не должна превратиться в ссылку."""
    assert canonicalize("пиши в https://t.me/bolatbekermekov", CONTACTS) == \
        "пиши в https://t.me/bolatbek_yermekov"
    assert canonicalize("t.me/bolatbekermekov", CONTACTS) == "t.me/bolatbek_yermekov"


def test_any_other_linkedin_profile_becomes_ours():
    got = canonicalize("LinkedIn: https://www.linkedin.com/in/bolatbekermekov/", CONTACTS)
    assert got == f"LinkedIn: {CONTACTS.linkedin}"


def test_an_email_address_is_not_mistaken_for_a_handle():
    """В «…50@gmail.com» тоже есть «@», и подмена сломала бы адрес."""
    assert canonicalize("Email: ermekovbolatbek50@gmail.com", CONTACTS) == \
        "Email: ermekovbolatbek50@gmail.com"


def test_a_job_link_is_left_alone():
    """Профиль это /in/. Ссылка на вакансию принадлежит работодателю."""
    text = "https://www.linkedin.com/jobs/view/4123456789/"
    assert canonicalize(text, CONTACTS) == text


def test_without_contacts_nothing_is_touched():
    assert canonicalize("@whoever", Contacts()) == "@whoever"


# --- письмо -----------------------------------------------------------------

class _Ai:
    def __init__(self, body, note=""):
        self._body, self._note = body, note

    def generate(self, **kwargs):
        return self._body

    def generate_with_note(self, **kwargs):
        return self._body, self._note


def test_the_letter_carries_only_our_handle():
    """Модель видит CV, где записан старый ник, и переносит его в текст."""
    gen = GenerateMessage(_Ai("Пишите мне в @bolatbekermekov"), "cv", "profile", SIGN)
    body = gen.execute(_lead())
    assert "@bolatbekermekov" not in body
    assert body.count("@bolatbek_yermekov") == 2      # в тексте и в подписи


def test_the_note_carries_only_our_handle_too():
    gen = GenerateMessage(_Ai("письмо", "записка, ник @bolatbekermeko_v"),
                          "cv", "profile", SIGN)
    _letter, note = gen.execute_with_note(_lead(), note_limit=200)
    assert note == "записка, ник @bolatbek_yermekov"


def test_a_generator_without_a_signature_leaves_the_text_as_it_is():
    """Канона нет — значит и правды о контактах нам не задали."""
    gen = GenerateMessage(_Ai("ник @somebody_else"), "cv", "profile", "")
    assert gen.execute(_lead()) == "ник @somebody_else"


# --- форма отклика ----------------------------------------------------------

def test_the_apply_profile_takes_its_contacts_from_the_signature(tmp_path):
    """В YAML их переписали руками, и копия разошлась с оригиналом."""
    path = tmp_path / "apply_profile.yml"
    path.write_text('full_name: "B Y"\n'
                    'linkedin: "https://www.linkedin.com/in/bolatbekermekov/"\n'
                    'custom_answers:\n'
                    '  "telegram handle": "@bolatbekermeko_v"\n', encoding="utf-8")
    prof = load_apply_profile(str(path), CONTACTS)
    assert prof.linkedin == CONTACTS.linkedin
    assert prof.telegram == "@bolatbek_yermekov"
    assert prof.custom_answers["telegram handle"] == "@bolatbek_yermekov"


def test_a_missing_profile_file_still_knows_the_contacts(tmp_path):
    prof = load_apply_profile(str(tmp_path / "nope.yml"), CONTACTS)
    assert prof.telegram == "@bolatbek_yermekov"
    assert prof.linkedin == CONTACTS.linkedin


def test_without_contacts_the_yaml_wins_as_before(tmp_path):
    path = tmp_path / "apply_profile.yml"
    path.write_text('linkedin: "https://www.linkedin.com/in/whoever/"\n', encoding="utf-8")
    assert load_apply_profile(str(path)).linkedin == \
        "https://www.linkedin.com/in/whoever/"


def test_a_telegram_field_on_a_form_is_filled_from_the_profile():
    from app.application.auto_apply import map_field
    from app.domain.page_observation import FieldObs

    prof = ApplyProfile(full_name="B Y", telegram="@bolatbek_yermekov")
    action = map_field(FieldObs(tag="input", type="text", label="Telegram handle",
                                name="tg"), prof, "/cv.pdf")
    assert action.value == "@bolatbek_yermekov"
    assert action.source == "profile"


# --- ответы модели ----------------------------------------------------------

def test_model_answers_are_brought_to_the_same_handle():
    answers = {"0": {"text": "мой телеграм @bolatbekermekov"}, "1": {"choice": 2}}
    got = canonicalize_answers(answers, CONTACTS)
    assert got["0"]["text"] == "мой телеграм @bolatbek_yermekov"
    assert got["1"] == {"choice": 2}


def test_model_answers_are_untouched_without_contacts():
    answers = {"0": {"text": "@whoever"}}
    assert canonicalize_answers(answers, None) == answers
