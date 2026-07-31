"""A missing apply_profile.yml must be loud, not silently empty.

`load_apply_profile` returns a default-constructed ApplyProfile when the file is
absent, so every external form parks the lead as `manual` with a note naming the
ATS's required fields — which reads like the form was exotic, not like the file
was never created. EXTERNAL_APPLY_ENABLED defaults to true, so this is the state
a fresh checkout runs in.
"""
from app.domain.apply_profile import ApplyProfile
from app.infrastructure.apply_profile_loader import load_apply_profile


def test_a_default_profile_is_blank():
    assert ApplyProfile().is_blank() is True


def test_a_missing_file_loads_a_blank_profile(tmp_path):
    assert load_apply_profile(str(tmp_path / "nope.yml")).is_blank() is True


def test_an_empty_yaml_file_is_blank_too(tmp_path):
    p = tmp_path / "apply_profile.yml"
    p.write_text("# всё закомментировано\n", encoding="utf-8")
    assert load_apply_profile(str(p)).is_blank() is True


def test_a_name_alone_is_enough_to_count_as_filled():
    assert ApplyProfile(full_name="Ivan Ivanov").is_blank() is False
    assert ApplyProfile(first_name="Ivan").is_blank() is False
    assert ApplyProfile(email="ivan@example.com").is_blank() is False


def test_contact_details_without_a_name_or_email_are_still_blank():
    """A phone and a city fill nothing an ATS asks for first."""
    assert ApplyProfile(phone="+7 777", city="Алматы").is_blank() is True


def test_whitespace_is_not_a_filled_field():
    assert ApplyProfile(full_name="   ", email=" \n").is_blank() is True


def test_the_shipped_example_file_is_a_filled_profile():
    """The template exists to be copied — copying it must produce a usable file."""
    from pathlib import Path
    example = Path(__file__).resolve().parents[1] / "apply_profile.example.yml"
    assert example.exists()
    profile = load_apply_profile(str(example))
    assert profile.is_blank() is False
    assert profile.custom_answers                     # keys lowercased on load
    assert all(k == k.lower() for k in profile.custom_answers)
