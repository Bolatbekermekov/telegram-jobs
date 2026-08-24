"""Fields that move under us mid-fill, and the resume that quietly never attached.

Measured on Ashby (2026-07-29, Higgsfield application): setting the first file
input re-renders the form, and the REQUIRED «Resume» input two nodes later comes
back as a fresh node without our `data-af` tag. The fill loop skipped it — a
missing element read as "nothing to do" — and `unmapped_required()` saw nothing
wrong because it reads the PLAN, not the page. The application went out with no
resume, Ashby rejected it, and all we reported was "no confirmation".
"""
import pytest

from app.application.auto_apply import build_plan
from app.domain.apply_profile import ApplyProfile
from app.domain.channel import ManualApplyRequired
from app.domain.page_observation import FieldObs, PageObservation
from app.infrastructure.channels import external_apply as ea

PROFILE = ApplyProfile(full_name="Bolatbek Yermekov", email="a@b.com")

# Прикрепление файла живёт в `widgets/file_upload.py` и проверяется там — на
# настоящей разметке и в настоящем браузере (Dropzone у Teamtailor удаляет вход
# из DOM, и доказательство приходится искать в отправляемых полях). Здесь
# страница фейковая: ни DOM, ни виджета у неё нет, а проверяются решения
# `fill_fields` — на каком поле он зовёт прикрепление и что делает с отказом.
@pytest.fixture(autouse=True)
def _stub_attach_file(monkeypatch):
    def fake(page, locator, path, **kw):
        if locator.count() == 0:
            return False
        locator.first.set_input_files(path)
        return bool(page.files.get(locator.sel, 0))
    monkeypatch.setattr(ea, "_attach_file", fake)


DECOY = FieldObs(tag="input", type="file", label="", required=False, ref="0")
RESUME = FieldObs(tag="input", type="file", label="Resume", required=True, ref="3")
NAME = FieldObs(tag="input", type="text", label="Name", required=True, ref="1")


class _Loc:
    def __init__(self, page, sel, n):
        self.page, self.sel, self._n = page, sel, n
        self.first = self

    def count(self):
        return self._n

    def set_input_files(self, path, **kw):
        self.page.uploads.append((self.sel, path))
        self.page.order.append("upload")
        self.page.on_upload(self.sel)

    def fill(self, v, **kw):
        self.page.filled[self.sel] = v
        self.page.order.append("fill")

    def evaluate(self, js, **kw):
        return self.page.files.get(self.sel, 0)


class _Page:
    """A form whose refs go stale once a file is set, like a React ATS."""

    def __init__(self, fields, stale_after_upload=True, resume_ever_attaches=True):
        self._fields = list(fields)
        self._stale = False
        self._stale_after_upload = stale_after_upload
        self._resume_ok = resume_ever_attaches
        self.uploads, self.filled, self.files = [], {}, {}
        self.order = []          # "upload" / "fill", in the sequence they happened
        self.scrapes = 0

    def on_upload(self, sel):
        # The upload lands, and the form re-renders around it.
        if sel == '[data-af="0"]':
            self.files[sel] = 1
            if self._stale_after_upload:
                self._stale = True          # every other data-af tag is dropped
        else:
            self.files[sel] = 1 if self._resume_ok else 0

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, js, *a):
        # scrape_form re-stamps the DOM, so tags are valid again afterwards.
        self.scrapes += 1
        self._stale = False
        return ea.observation_to_raw(PageObservation(url="https://ats/x",
                                                     fields=self._fields))

    def locator(self, sel):
        known = {f'[data-af="{f.ref}"]' for f in self._fields}
        if sel not in known:
            return _Loc(self, sel, 0)
        # A stale page only still answers for the field that was just uploaded.
        if self._stale and sel != '[data-af="0"]':
            return _Loc(self, sel, 0)
        return _Loc(self, sel, 1)


def test_a_required_field_that_lost_its_tag_is_found_again():
    """Резюме доезжает до СВОЕГО поля, даже когда форма перерисовалась.

    Проверка «а был ли повторный поиск» отсюда ушла вместе с самим поиском: его
    делает `widgets/file_upload.py`, и делает не по нашему локатору, а по
    приметам входа — у Teamtailor узла с этим id в DOM нет вовсе те 800 мс, пока
    файл летит в хранилище. Там это и закреплено. Здесь остаётся то, за что
    отвечает `fill_fields`: на какое поле уходит какой файл."""
    page = _Page([DECOY, NAME, RESUME])
    ea.fill_fields(page, build_plan(PageObservation(fields=[DECOY, NAME, RESUME]),
                                    PROFILE, "cv.pdf"))

    assert ('[data-af="3"]', "cv.pdf") in page.uploads      # the real resume
    assert not any(sel == '[data-af="0"]' for sel, _ in page.uploads)


def test_the_resume_is_verified_on_a_freshly_found_element():
    """The old handle reports the file it swallowed; only a fresh lookup tells the
    truth about the live input."""
    page = _Page([DECOY, RESUME])
    ea.fill_fields(page, build_plan(PageObservation(fields=[DECOY, RESUME]),
                                    PROFILE, "cv.pdf"))
    assert page.files['[data-af="3"]'] == 1


def test_a_resume_that_never_attaches_stops_the_application():
    """Better a manual apply than a submitted form with no CV in it."""
    page = _Page([DECOY, RESUME], resume_ever_attaches=False)
    with pytest.raises(ManualApplyRequired, match="резюме не прикрепилось"):
        ea.fill_fields(page, build_plan(PageObservation(fields=[DECOY, RESUME]),
                                        PROFILE, "cv.pdf"))


def test_a_required_text_field_that_vanishes_entirely_is_not_skipped():
    """A missing required control must never read as "nothing to do"."""
    ghost = FieldObs(tag="input", type="text", label="Ghost", required=True, ref="9")
    page = _Page([DECOY])                      # the plan knows a field the page lost
    plan = build_plan(PageObservation(fields=[ghost]), PROFILE, "cv.pdf")
    plan.actions[0].value = "something"

    with pytest.raises(ManualApplyRequired, match="исчезло со страницы"):
        ea.fill_fields(page, plan)


def test_an_optional_field_that_vanishes_is_still_skipped_quietly():
    optional = FieldObs(tag="input", type="text", label="Twitter", required=False, ref="9")
    page = _Page([DECOY])
    plan = build_plan(PageObservation(fields=[optional]), PROFILE, "cv.pdf")
    plan.actions[0].value = "@x"

    ea.fill_fields(page, plan)                 # must not raise
    assert page.filled == {}


# --- the upload that is not part of the application --------------------------

def test_only_the_named_resume_field_receives_the_cv():
    """Ashby's unlabelled "Autofill from resume" dropzone sits above the real form.
    Uploading there makes the server rebuild the form under us — 22 setFormValue
    calls went to a render id that no longer existed, and the Submit fired no
    request at all (lead 123, 2026-07-29)."""
    plan = build_plan(PageObservation(fields=[DECOY, RESUME]), PROFILE, "cv.pdf")
    files = [a for a in plan.actions if a.is_file]

    assert [a.field.label for a in files] == ["Resume"]


def test_a_lone_unlabelled_file_input_is_still_used():
    """Plenty of forms have exactly one upload and no caption for it."""
    plan = build_plan(PageObservation(fields=[DECOY]), PROFILE, "cv.pdf")
    assert [a.is_file for a in plan.actions] == [True]


def test_a_russian_resume_caption_counts_as_named():
    ru = FieldObs(tag="input", type="file", label="Резюме", required=True, ref="2")
    plan = build_plan(PageObservation(fields=[DECOY, ru]), PROFILE, "cv.pdf")
    files = [a for a in plan.actions if a.is_file]
    assert [a.field.label for a in files] == ["Резюме"]


def test_uploads_happen_before_the_other_fields():
    """Every upload rebuilds the form on the server, discarding values written to
    the previous render. Filling in DOM order sent most of them into the void."""
    page = _Page([NAME, RESUME], stale_after_upload=False)
    ea.fill_fields(page, build_plan(PageObservation(fields=[NAME, RESUME]),
                                    PROFILE, "cv.pdf"))

    assert page.uploads, "резюме должно было загрузиться"
    assert page.order.index("upload") < page.order.index("fill")
