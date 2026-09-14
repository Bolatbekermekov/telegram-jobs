"""Почтовый индекс — не «город, страна», даже если в имени поля есть «location».

Живьём 2026-09-14 (Indeed Apply, #1236, прогон 9): экран «Add your location» —
поле «Zip code» с `name="location-postal-code"`. Правило места читает подпись
вместе с именем поля, нашло там «location» и вписало «Astana, Kazakhstan» в
индекс; форма не приняла экран. Индекса в анкете нет, и выдумывать его нельзя.
"""
from app.application.auto_apply import map_field
from app.domain.apply_profile import ApplyProfile
from app.domain.page_observation import FieldObs

PROFILE = ApplyProfile(full_name="Bolatbek Yermekov", email="a@b.com", city="Astana",
                       country="Kazakhstan")


def _map(**kw):
    return map_field(FieldObs(tag="input", type="text", **kw), PROFILE, "/cv.pdf")


def test_a_zip_code_named_location_is_not_filled_with_the_city():
    a = _map(label="Zip code", name="location-postal-code")
    assert (a.value, a.source) == ("", "unmapped")


def test_postal_code_captions_in_both_languages_stay_empty():
    for label in ("Postal code", "Post code", "ZIP", "Почтовый индекс"):
        a = _map(label=label, name="address-postal")
        assert a.value == "", label


def test_the_city_next_to_it_is_still_the_city():
    a = _map(label="City", name="location-locality")
    assert a.value == "Astana"


def test_a_street_address_named_location_is_not_filled_with_the_city():
    """Индекс починили, а в тот же прогон (#1236, прогон 10) «Street address» с
    `name="location-address"` получил «Astana, Kazakhstan». Улицы в анкете нет."""
    a = _map(label="Street address", name="location-address")
    assert (a.value, a.source) == ("", "unmapped")


def test_an_email_address_is_still_the_email():
    a = map_field(FieldObs(tag="input", type="email", label="Email address", name="email"),
                  ApplyProfile(full_name="B Y", email="a@b.com"), "/cv.pdf")
    assert a.value == "a@b.com"
