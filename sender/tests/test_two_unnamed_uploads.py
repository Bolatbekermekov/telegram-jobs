"""Две одинаково безымянные загрузки: резюме уходит только в первую.

Замер живьём 2026-09-17 (careerplug, `eitacies-inc.careerplug.com/jobs/3597035/
apps/new`, лид #1409): на форме два поля `type=file`, оба подписаны «Upload File»,
оба необязательные. Настоящие заголовки «Resume/CV» и «Cover Letter» лежат на
5–7 уровней выше в DOM, и скрапер до них не дотягивается.

`_only_the_real_resume_field` отсекает лишние загрузки только когда ХОТЬ ОДНА
названа резюме. Здесь не названа ни одна — правило пропускало обе, и работодатель
получал резюме дважды, второй раз вместо сопроводительного письма. Это не опасно,
но выглядит небрежно, а заметить это со стороны владельца некому.

Первая загрузка на форме — по соглашению резюме, письмо идёт следом.
"""
from app.application.auto_apply import build_plan
from app.domain.apply_profile import ApplyProfile
from app.domain.page_observation import FieldObs, PageObservation

PROFILE = ApplyProfile(full_name="Bolatbek Yermekov")
CV = "/cv/ai/Bolatbek_Yermekov_AI_Engineer.pdf"


def _upload(ref, label="Upload File"):
    return FieldObs(tag="input", type="file", label=label, name="", required=False,
                    options=[], value="", combobox=False, ref=ref)


def _plan(*fields):
    return build_plan(PageObservation(url="https://x.careerplug.com/jobs/1/apps/new",
                                      fields=list(fields)), PROFILE, CV)


def test_only_the_first_of_two_unnamed_uploads_gets_the_cv():
    files = [a for a in _plan(_upload("1"), _upload("2")).actions if a.is_file]

    assert len(files) == 1
    assert files[0].value == CV


def test_a_lone_unnamed_upload_still_gets_the_cv():
    """Одна безымянная загрузка — это и есть поле резюме, её трогать нельзя."""
    files = [a for a in _plan(_upload("1")).actions if a.is_file]

    assert len(files) == 1
    assert files[0].value == CV


def test_a_named_resume_field_still_wins_over_an_unnamed_one():
    """Когда резюме названо прямо, выбирать надо ЕГО, а не первое по порядку."""
    files = [a for a in _plan(_upload("1"), _upload("2", label="Resume/CV")).actions
             if a.is_file]

    assert len(files) == 1
    assert files[0].field.label == "Resume/CV"
