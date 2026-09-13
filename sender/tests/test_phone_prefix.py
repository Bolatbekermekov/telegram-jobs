"""Список «Phone prefix» получает код страны из профиля, а номер — без кода.

Живьём 2026-09-13, Factorial (лид #1044): рядом с «Phone *» стоит
`<select name="phone_prefix">` со «Spain (+34)» по умолчанию. Правило телефона
искало среди вариантов весь номер «+7 775 720 0604», не нашло, и список остался на
Испании, а в «Phone» ушёл номер с +7. После «Submit» сервер ответил «Something
went wrong. Try again later.», форма осталась на месте. Прежнее правило про код
страны знало только подпись «country code» (LinkedIn Easy Apply).
"""
from app.application.auto_apply import build_plan
from app.domain.apply_profile import ApplyProfile
from app.domain.page_observation import FieldObs, PageObservation

PROF = ApplyProfile(full_name="Bolatbek Yermekov", phone="+7 775 720 0604", country="Kazakhstan")


def _plan(prefix_label="Phone prefix", options=None):
    prefix = FieldObs(tag="select", type="select-one", label=prefix_label, name="phone_prefix",
                      options=options or ["Spain (+34)", "Russian Federation (+7)",
                                          "Kazakhstan (+7)", "Kenya (+254)"], ref="2")
    phone = FieldObs(tag="input", type="text", label="Phone *", name="phone",
                     required=True, ref="3")
    return build_plan(PageObservation(fields=[prefix, phone]), PROF, "/cv.pdf").actions


def test_the_prefix_list_takes_the_profile_country():
    prefix, _ = _plan()
    assert prefix.value == "Kazakhstan (+7)"
    assert prefix.choice_index == 2


def test_the_number_goes_without_the_code_it_already_got():
    _, phone = _plan()
    assert phone.value == "775 720 0604"


def test_the_code_alone_decides_when_the_country_is_not_listed():
    prefix, _ = _plan(options=["Spain (+34)", "+7", "+254"])
    assert prefix.value == "+7"


def test_a_dial_code_caption_is_the_same_question():
    prefix, phone = _plan(prefix_label="Dial code")
    assert prefix.value == "Kazakhstan (+7)" and phone.value == "775 720 0604"
