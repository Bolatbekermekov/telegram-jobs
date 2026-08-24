"""Did the application actually land, and typeaheads that must be picked, not typed.

Both come from the same run (2026-07-29). Every Ashby application reported
«отправка не подтверждена» while the click had gone through — leads 119, 127, 128,
129 — because the check was "is a submit button still on the page", and
`SEL_SUBMIT` matches `button:has-text('Apply')`, which a confirmation page keeps.
And LinkedIn's «Location (city)» rejected typed text with "Please enter a valid
answer" (lead 126): it is a combobox, and only its own suggestions count.
"""
import pytest

from app.application.auto_apply import build_plan
from app.domain.apply_profile import ApplyProfile
from app.domain.channel import ManualApplyRequired
from app.domain.page_observation import FieldObs, PageObservation
from app.infrastructure.channels import external_apply as ea

PROFILE = ApplyProfile(full_name="Bolatbek Yermekov", first_name="Bolatbek",
                       email="a@b.com", city="Astana")
# The selector _visible_error uses; kept in one place so a change there shows up
# as a test failure rather than as a fake that silently reports nothing.
ERR_SEL = ("[role=alert], [aria-invalid='true'], "
           "[class*=error i], [class*=Error]")


class _Loc:
    def __init__(self, page, sel):
        self.page, self.sel = page, sel
        self.first = self

    def count(self):
        return self.page.counts.get(self.sel, 0)

    def nth(self, i):
        return self

    def inner_text(self, timeout=None):
        return self.page.texts.get(self.sel, "")

    def click(self, timeout=None, force=False):
        self.page.clicks.append(self.sel)

    def fill(self, v, **kw):
        self.page.filled[self.sel] = v

    def type(self, v, delay=None):
        self.page.typed.setdefault(self.sel, []).append(v)


class _Page:
    def __init__(self, text="", url="https://ats.example/apply", fields=(), counts=None):
        self.body, self.url, self._fields = text, url, list(fields)
        # Every scraped field is addressable, like a real page.
        self.counts = {f'[data-af="{f.ref}"]': 1 for f in self._fields}
        self.counts.update(counts or {})
        self.texts, self.clicks, self.filled, self.typed = {}, [], {}, {}

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, js, *a):
        if "innerText" in js and "slice(0, 4000)" in js:
            return self.body
        return ea.observation_to_raw(PageObservation(url=self.url, fields=self._fields))

    def locator(self, sel):
        return _Loc(self, sel)


# --- did it land? -----------------------------------------------------------

def test_a_thank_you_page_counts_as_submitted():
    page = _Page(text="Thank you for applying! We have received your application.")
    ea._verify_submitted(page, "https://ats.example/apply")     # must not raise


def test_a_russian_confirmation_counts_too():
    ea._verify_submitted(_Page(text="Спасибо за отклик! Заявка отправлена."), "u")


def test_leaving_the_form_page_counts_as_submitted():
    page = _Page(text="", url="https://ats.example/apply")
    page.url = "https://ats.example/thanks"          # navigated after the click
    ea._verify_submitted(page, "https://ats.example/apply")


def test_a_form_that_is_gone_counts_as_submitted():
    ea._verify_submitted(_Page(text="", fields=[]), "https://ats.example/apply")


def test_an_unreadable_outcome_warns_that_it_may_already_be_sent():
    """The wording matters more than the status: the human's next move is either
    to apply again or not, and «не подтверждена» told them to."""
    page = _Page(text="Apply now", fields=[FieldObs(tag="input", label="Email", ref="0")])
    with pytest.raises(ManualApplyRequired) as err:
        ea._verify_submitted(page, "https://ats.example/apply")

    said = str(err.value)
    assert "ВОЗМОЖНО, ЗАЯВКА УЖЕ УШЛА" in said
    assert "проверь почту" in said


def test_a_visible_validation_error_is_reported_verbatim():
    page = _Page(text="Apply now", fields=[FieldObs(tag="input", label="Email", ref="0")],
                 counts={ERR_SEL: 1})
    page.texts[ERR_SEL] = "Please enter a valid answer"

    with pytest.raises(ManualApplyRequired, match="Please enter a valid answer"):
        ea._verify_submitted(page, "https://ats.example/apply")


def test_the_word_apply_alone_is_not_a_confirmation():
    """`SEL_SUBMIT` matching 'Apply' is what made every Ashby send look failed;
    the success phrases must not repeat that mistake."""
    for benign in ("Apply now", "Application form", "Easy Apply", "Подать заявку"):
        assert ea._SUBMITTED_RE.search(benign) is None


# --- typeaheads -------------------------------------------------------------

# Как ИМЕННО набирается запрос и выбирается подсказка — забота
# `widgets/combobox.py`, и проверяется она там: на копии разметки react-select и
# в настоящем браузере. Прежние тесты пиновали здесь набор и клик по общему
# селектору подсказок — и пережить это не могли: замер 2026-08-24 показал, что
# такой селектор ловит на форме Greenhouse 254 варианта, из которых 244 — скрытый
# список стран телефонного виджета, и клик уходил в невидимую «Afghanistan».
# Здесь остаётся то, за что отвечает `fill_fields`: какое значение он несёт
# виджету и что делает с отказом.

def _spy_combobox(monkeypatch, answer=True):
    calls = []

    def fake(page, locator, value, **kw):
        calls.append(value)
        return answer

    monkeypatch.setattr(ea, "_fill_combobox", fake)
    return calls


def test_a_combobox_gets_its_value_through_the_widget(monkeypatch):
    field = FieldObs(tag="input", type="text", label="Location (city)",
                     required=True, combobox=True, ref="0")
    calls = _spy_combobox(monkeypatch)
    ea.fill_fields(_Page(fields=[field]),
                   build_plan(PageObservation(fields=[field]), PROFILE, "cv.pdf"))
    assert calls == ["Astana"]


def test_a_plain_text_field_is_still_filled_not_typed():
    field = FieldObs(tag="input", type="text", label="First name", required=True, ref="0")
    page = _Page(fields=[field])
    plan = build_plan(PageObservation(fields=[field]), PROFILE, "cv.pdf")

    ea.fill_fields(page, plan)

    assert page.filled['[data-af="0"]'] == "Bolatbek"
    assert '[data-af="0"]' not in page.typed


def test_a_combobox_that_offered_nothing_fitting_stops_a_required_field(monkeypatch):
    """Раньше набранный текст просто оставался в поле. Для типа, который
    принимает ТОЛЬКО свои варианты, это отправка мусора: форма либо отвергнет
    её, либо запишет не то. Замер 2026-08-24: `Bachelors Degree` даёт у Datadog
    ноль вариантов, а `Bachelor` — «Bachelor's Degree»; промах здесь обычное
    дело. Виджет в таком случае оставляет поле пустым, а обязательное поле
    честно уходит в ручной отклик."""
    field = FieldObs(tag="input", type="text", label="Location (city)",
                     required=True, combobox=True, ref="0")
    _spy_combobox(monkeypatch, answer=False)
    with pytest.raises(ManualApplyRequired, match="не выбрался вариант"):
        ea.fill_fields(_Page(fields=[field]),
                       build_plan(PageObservation(fields=[field]), PROFILE, "cv.pdf"))


def test_a_combobox_the_form_did_not_require_is_skipped_quietly(monkeypatch):
    field = FieldObs(tag="input", type="text", label="Location (city)",
                     required=False, combobox=True, ref="0")
    _spy_combobox(monkeypatch, answer=False)
    ea.fill_fields(_Page(fields=[field]),
                   build_plan(PageObservation(fields=[field]), PROFILE, "cv.pdf"))


def test_the_pressed_button_vanishing_counts_as_submitted():
    """Weaker than a thank-you page, but unambiguous: there was one submit button
    and now there is none. Compared against a count taken BEFORE the click, so a
    page whose only match was a stray «Apply» link cannot fake it."""
    page = _Page(text="", fields=[FieldObs(tag="input", label="Email", ref="0")],
                 counts={ea.SEL_SUBMIT: 0})
    ea._verify_submitted(page, "https://ats.example/apply", submit_before=1)


def test_a_button_that_was_never_there_is_not_a_signal():
    page = _Page(text="", fields=[FieldObs(tag="input", label="Email", ref="0")],
                 counts={ea.SEL_SUBMIT: 0})
    with pytest.raises(ManualApplyRequired, match="ВОЗМОЖНО"):
        ea._verify_submitted(page, "https://ats.example/apply", submit_before=0)


def test_a_button_still_on_the_page_is_not_a_signal():
    page = _Page(text="", fields=[FieldObs(tag="input", label="Email", ref="0")],
                 counts={ea.SEL_SUBMIT: 1})
    with pytest.raises(ManualApplyRequired, match="ВОЗМОЖНО"):
        ea._verify_submitted(page, "https://ats.example/apply", submit_before=1)


# --- the ATS refusing us as a bot -------------------------------------------

def test_a_spam_flag_is_reported_as_bot_detection_not_a_form_problem():
    """Ashby's real answer, measured 2026-07-29 after a live submit: the form
    stays, no field is invalid, and the page says the submission was flagged as
    spam. Nothing in the form can be fixed — only a human can send this one."""
    url = "https://jobs.ashbyhq.com/x/application"
    page = _Page(text="We couldn't submit your application. Your application "
                      "submission was flagged as possible spam.",
                 url=url, fields=[FieldObs(tag="input", label="Email", ref="0")])
    with pytest.raises(ManualApplyRequired) as err:
        ea._verify_submitted(page, url)

    said = str(err.value)
    assert "антибот" in said
    assert "вручную" in said
    assert "ВОЗМОЖНО" not in said       # not the ambiguous outcome


def test_a_captcha_challenge_reads_the_same_way():
    page = _Page(text="Please verify you are human before continuing.",
                 fields=[FieldObs(tag="input", label="Email", ref="0")])
    with pytest.raises(ManualApplyRequired, match="антибот"):
        ea._verify_submitted(page, "https://ats.example/apply")


def test_an_ordinary_validation_error_is_still_reported_as_itself():
    page = _Page(text="Apply now", fields=[FieldObs(tag="input", label="Email", ref="0")],
                 counts={ERR_SEL: 1})
    page.texts[ERR_SEL] = "Please enter a valid answer"

    with pytest.raises(ManualApplyRequired) as err:
        ea._verify_submitted(page, "https://ats.example/apply")
    assert "антибот" not in str(err.value)


def test_a_banner_at_the_bottom_of_a_long_page_is_still_read():
    """Ashby puts its verdict after the entire job description. Reading only the
    head of the page saw none of it, and a refusal the code already knew how to
    name still came out as "no confirmation"."""
    url = "https://jobs.ashbyhq.com/x/application"
    long_page = ("описание вакансии " * 400 +
                 "Your application submission was flagged as possible spam.")
    page = _Page(text=long_page, url=url,
                 fields=[FieldObs(tag="input", label="Email", ref="0")])
    with pytest.raises(ManualApplyRequired, match="антибот"):
        ea._verify_submitted(page, url)


def test_a_confirmation_at_the_bottom_counts_too():
    long_page = "описание вакансии " * 400 + "Thank you for applying!"
    ea._verify_submitted(_Page(text=long_page,
                               fields=[FieldObs(tag="input", label="Email", ref="0")]),
                         "https://ats.example/apply")
