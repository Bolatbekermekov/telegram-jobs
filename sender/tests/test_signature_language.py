"""Подпись обязана быть на языке письма.

Подпись НЕ пишет модель: это фиксированный блок из sender/signature.txt, и
приклеивается он уже после генерации (GenerateMessage.execute). Поэтому
language_rule на неё не действует вовсе — английское письмо уезжало с русским
«С уважением, Bolatbek» в конце, и получатель видел одно русское слово в
безупречно английском тексте.

Контакты трогать нечего: «Telegram:», «Email:», «LinkedIn:» одинаковы в обоих
языках. Меняется ровно строка прощания.
"""
from app.domain.signature import localize_signature

SIGNATURE = ("С уважением, Bolatbek\n"
             "Telegram: @bolatbekermeko_v\n"
             "Email: ermekovbolatbek50@gmail.com\n"
             "LinkedIn: https://www.linkedin.com/in/bolatbekermekov/")


def test_an_english_letter_gets_an_english_sign_off():
    got = localize_signature(SIGNATURE, "en")
    assert got.splitlines()[0] == "Best regards, Bolatbek"


def test_the_contacts_are_left_exactly_as_they_are():
    """Ссылки и адреса — не текст для перевода, любая правка тут это опечатка
    в контакте, по которому с тобой должны связаться."""
    got = localize_signature(SIGNATURE, "en")
    assert got.splitlines()[1:] == SIGNATURE.splitlines()[1:]


def test_a_russian_letter_keeps_the_russian_sign_off():
    assert localize_signature(SIGNATURE, "ru") == SIGNATURE


def test_an_already_english_signature_is_not_touched_twice():
    """Если человек однажды перепишет signature.txt по-английски, подпись не
    должна превратиться в «Best regards, Best regards, Bolatbek»."""
    english = SIGNATURE.replace("С уважением, Bolatbek", "Best regards, Bolatbek")
    assert localize_signature(english, "en") == english


def test_an_unknown_sign_off_is_left_alone():
    """Незнакомая формулировка — не повод угадывать: лучше оставить как есть,
    чем подставить чужое имя или потерять строку."""
    other = "Спасибо!\nTelegram: @x"
    assert localize_signature(other, "en") == other


def test_an_empty_signature_stays_empty():
    for value in ("", None, "   "):
        assert localize_signature(value, "en") == ""


def test_the_name_survives_whatever_it_is():
    assert localize_signature("С уважением, Иван Петров", "en") == "Best regards, Иван Петров"


def test_a_sign_off_without_a_comma_still_works():
    assert localize_signature("С уважением Bolatbek", "en") == "Best regards, Bolatbek"


# --- проводка: подпись выбирается по языку самой вакансии --------------------

from app.application.generate_message import GenerateMessage   # noqa: E402
from app.domain.lead import Lead                                # noqa: E402

EN_JOB = ("Senior Backend Engineer (Go). We are looking for an engineer to build "
          "distributed services. Remote, full-time, competitive salary.")
RU_JOB = ("Ищем backend-разработчика на Go. Удалённая работа, полный день, "
          "команда из десяти человек, конкурентная зарплата.")


class _Ai:
    def generate(self, cv_text, profile_text, vacancy_context, language=""):
        return "Letter body."

    def generate_with_note(self, cv_text, profile_text, vacancy_context,
                           note_limit, language=""):
        return "Letter body.", "Note."


def _lead(vacancy):
    return Lead(row=2, lead_id="1", platform="telegram", target="@x",
                vacancy_context=vacancy, raw_text=vacancy, status="new")


def test_an_english_vacancy_produces_a_fully_english_letter():
    """Ровно та жалоба: письмо целиком по-английски и «С уважением» в конце."""
    got = GenerateMessage(_Ai(), "CV", "PROFILE", SIGNATURE).execute(_lead(EN_JOB))
    assert "Best regards, Bolatbek" in got
    assert "уважением" not in got


def test_a_russian_vacancy_keeps_the_russian_sign_off():
    got = GenerateMessage(_Ai(), "CV", "PROFILE", SIGNATURE).execute(_lead(RU_JOB))
    assert "С уважением, Bolatbek" in got


def test_the_note_path_localises_the_signature_too():
    """LinkedIn идёт другим методом, и забыть его — значит починить половину."""
    letter, _note = GenerateMessage(_Ai(), "CV", "PROFILE", SIGNATURE).execute_with_note(
        _lead(EN_JOB), note_limit=200)
    assert "Best regards, Bolatbek" in letter
    assert "уважением" not in letter


def test_the_language_comes_from_the_vacancy_not_from_the_letter():
    """Язык берётся из того же текста, что и правило для модели, — иначе письмо
    и подпись могут разъехаться, когда модель ошиблась языком."""
    lead = Lead(row=2, lead_id="1", platform="telegram", target="@x",
                vacancy_context="", raw_text=EN_JOB, status="new")
    got = GenerateMessage(_Ai(), "CV", "PROFILE", SIGNATURE).execute(lead)
    assert "Best regards, Bolatbek" in got
