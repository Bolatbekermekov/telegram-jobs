"""Вопросы формы по-французски, на которые ответ в анкете УЖЕ есть.

Замер живьём 2026-09-17, лид #1429 (Sia, LinkedIn Easy Apply, шаг 5): два
обязательных поля остались пустыми и увели заявку в ручные —

    «Quelle est votre date de disponibilité estimée ?»
    «Comment avez-vous entendu parler de Sia ?»

— при том, что в анкете стоят и `notice_period: "1-2 weeks"`, и готовый ответ
«how did you hear about us»: «LinkedIn». Готовые ответы сопоставляются по
СЛОВАМ ключа с подписью поля, а во французской подписи английских слов нет;
правило про выход на работу знало только английский и русский.

Отдельно — граница, которую это правило не переходит: в анкете стоит СРОК, а
не дата. Контрол, который требует именно дату, остаётся человеку: вычисленный
день выхода — утверждение о владельце, которого он не делал.
"""
from app.application.auto_apply import map_field
from app.domain.apply_profile import ApplyProfile
from app.domain.page_observation import FieldObs

PROFILE = ApplyProfile(
    full_name="Bolatbek Yermekov",
    notice_period="1-2 weeks",
    custom_answers={"how did you hear about us": "LinkedIn",
                    "notice period": "1-2 weeks"},
)

_AVAILABILITY = "Quelle est votre date de disponibilité estimée ?"
_HEARD = "Comment avez-vous entendu parler de Sia ?"


def _field(label, type_="text", options=(), required=True, **kw):
    return FieldObs(tag="input", type=type_, label=label, name="", required=required,
                    options=list(options), value="", combobox=False, ref="1", **kw)


def test_the_french_how_did_you_hear_question_gets_the_ready_answer():
    got = map_field(_field(_HEARD), PROFILE, "/cv.pdf")
    assert got.value == "LinkedIn"
    assert got.source == "custom"


def test_a_free_text_french_availability_question_gets_the_notice_period():
    """Свободный текст — отвечаем тем, что есть: сроком, а не датой."""
    got = map_field(_field(_AVAILABILITY), PROFILE, "/cv.pdf")
    assert got.value == "1-2 weeks"
    assert got.source == "profile"


def test_a_french_availability_date_control_is_left_to_the_human():
    """`input[type=date]` принимает только дату, а даты у нас нет — только срок."""
    got = map_field(_field(_AVAILABILITY, type_="date"), PROFILE, "/cv.pdf")
    assert got.source == "unmapped"
    assert not got.value


def test_a_french_availability_date_picker_is_left_to_the_human():
    """Календарь рядом с текстовым полем — тот же вопрос о ДАТЕ. Срок туда не
    встанет, а вычисленный день выхода уйдёт работодателю как слово владельца."""
    got = map_field(_field(_AVAILABILITY, date_picker=True), PROFILE, "/cv.pdf")
    assert got.source == "unmapped"
    assert not got.value


def test_a_french_availability_dropdown_still_goes_to_the_model():
    """Список пишет работодатель, и по-французски: «Sous 2 semaines». Считать
    дни по таким вариантам разбор сроков не умеет, а учить его языку, которого
    мы в живом списке ещё не видели, значило бы писать правило под выдуманный
    замер. Обязательный список отвечает модель — ровно как до этой правки."""
    got = map_field(_field(_AVAILABILITY, type_="select",
                           options=["Immédiatement", "Sous 2 semaines", "Sous 3 mois"]),
                    PROFILE, "/cv.pdf")
    assert got.needs_ai
    assert got.source == "ai"
