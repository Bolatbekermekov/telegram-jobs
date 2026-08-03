"""Поле-загрузка «Cover letter» получает письмо, а не резюме и не пустоту.

Замер 2026-08-03: такое поле возвращало `unmapped` — класть туда CV нельзя, а
другого файла не было. На обязательном поле это парковало всю заявку в
`manual`, хотя письмо под вакансию уже было написано.

Проверять надо оба направления: cover letter получает ПИСЬМО, а поле резюме
по-прежнему получает РЕЗЮМЕ. Перепутать их — значит отправить работодателю не
тот документ, и заметить это будет некому.
"""
from app.application.auto_apply import build_plan, map_field
from app.domain.apply_profile import ApplyProfile
from app.domain.page_observation import FieldObs, PageObservation

PROFILE = ApplyProfile(full_name="Bolatbek Yermekov")
CV = "/cv/backend-go/Bolatbek_Backend_Go.pdf"
LETTER = "/tmp/cover-x/cover_letter.pdf"


def _file_field(label, required=True, ref="1"):
    return FieldObs(tag="input", type="file", label=label, name="", required=required,
                    options=[], value="", combobox=False, ref=ref)


def test_a_cover_letter_upload_gets_the_letter():
    got = map_field(_file_field("Cover letter"), PROFILE, CV, cover_letter_path=LETTER)
    assert got.value == LETTER
    assert got.is_file is True


def test_the_resume_upload_still_gets_the_cv():
    got = map_field(_file_field("Resume/CV"), PROFILE, CV, cover_letter_path=LETTER)
    assert got.value == CV


def test_without_a_letter_the_field_stays_as_it_was():
    """Нет собранного PDF — поле пустое, как и до появления этой возможности.
    Подставлять туда резюме нельзя ни при каких условиях."""
    got = map_field(_file_field("Cover letter"), PROFILE, CV)
    assert got.source == "unmapped"
    assert got.value == ""


def test_other_document_uploads_are_still_left_alone():
    """Портфолио, фото и справки — не письмо и не резюме."""
    for label in ("Portfolio", "Photo", "Certificate"):
        got = map_field(_file_field(label), PROFILE, CV, cover_letter_path=LETTER)
        assert got.source == "unmapped", label


def test_the_plan_carries_both_documents():
    obs = PageObservation(url="https://ats.example/apply", fields=[
        _file_field("Resume", ref="0"), _file_field("Cover Letter", ref="1")])
    plan = build_plan(obs, PROFILE, CV, cover_letter_path=LETTER)

    by_ref = {a.field.ref: a.value for a in plan.actions}
    assert by_ref["0"] == CV
    assert by_ref["1"] == LETTER
