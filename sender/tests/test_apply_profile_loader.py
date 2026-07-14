from app.domain.apply_profile import ApplyProfile
from app.infrastructure.apply_profile_loader import load_apply_profile


def test_missing_file_returns_empty_profile(tmp_path):
    prof = load_apply_profile(str(tmp_path / "nope.yml"))
    assert isinstance(prof, ApplyProfile)
    assert prof.email == "" and prof.custom_answers == {}


def test_loads_fields_bools_and_lowercased_custom_answers(tmp_path):
    p = tmp_path / "apply_profile.yml"
    p.write_text(
        'full_name: "Bolatbek Yermekov"\n'
        'email: "a@b.com"\n'
        'needs_visa_sponsorship: false\n'
        'open_to_relocation: true\n'
        'phone:\n'                       # null -> coerced to ""
        'custom_answers:\n'
        '  "Years Of Experience": 3\n'   # non-str value -> str, key -> lowercase
        '  "why do you want": ""\n',
        encoding="utf-8",
    )
    prof = load_apply_profile(str(p))
    assert prof.full_name == "Bolatbek Yermekov"
    assert prof.needs_visa_sponsorship is False and prof.open_to_relocation is True
    assert prof.phone == ""
    assert prof.custom_answers["years of experience"] == "3"
    assert prof.custom_answers["why do you want"] == ""


def test_ignores_unknown_keys(tmp_path):
    p = tmp_path / "apply_profile.yml"
    p.write_text('email: "a@b.com"\nbogus_key: "x"\n', encoding="utf-8")
    prof = load_apply_profile(str(p))
    assert prof.email == "a@b.com"
    assert not hasattr(prof, "bogus_key")
