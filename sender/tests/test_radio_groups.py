"""Radio questions: one group, one answer, pressed on the right button.

Screening questions come as radios, and emitted one control at a time they carry
no options — nothing can answer them, and the form comes back "Please make a
selection". Measured live on 2026-07-29, LinkedIn job 4434515311: «Are you
comfortable working in an onsite setting?» was exactly that, and it was the last
thing between the walk and the submit button.
"""
import pytest

from app.application.auto_apply import (
    ApplyPlan, FillAction, build_plan, map_field,
)
from app.domain.channel import ManualApplyRequired
from app.domain.apply_profile import ApplyProfile
from app.domain.page_observation import FieldObs, PageObservation
from app.infrastructure.channels import external_apply as ea

PROFILE = ApplyProfile(full_name="Bolatbek Yermekov", email="a@b.com",
                       phone="+7 775 720 0604", open_to_relocation=True)

ONSITE_Q = FieldObs(
    tag="input", type="radio", name="onsite-urn:li:fsu_easyApplyFormElement",
    label="Are you comfortable working in an onsite setting?",
    required=True, options=["Yes", "No"], value="", ref="4")


class _Loc:
    def __init__(self, page, sel, n=1):
        self.page, self.sel, self._n = page, sel, n
        self.first = self

    def count(self):
        return self._n

    def nth(self, i):
        loc = _Loc(self.page, self.sel, self._n)
        loc._idx = i
        return loc

    def check(self, timeout=None, force=False):
        self.page.checked.append((self.sel, getattr(self, "_idx", None), force))

    def fill(self, v, **kw):
        self.page.filled[self.sel] = v

    def set_input_files(self, v, **kw):
        self.page.filled[self.sel] = ("file", v)

    def select_option(self, index=None, **kw):
        self.page.filled[self.sel] = ("choice", index)


class _Page:
    def __init__(self, group_size=2):
        self.checked, self.filled = [], {}
        self._group_size = group_size

    def locator(self, sel):
        n = self._group_size if sel.startswith("input[type=radio]") else 1
        return _Loc(self, sel, n)


def _plan_with(action_choice):
    plan = build_plan(PageObservation(fields=[ONSITE_Q]), PROFILE, "cv.pdf")
    plan.actions[0].choice_index = action_choice
    plan.actions[0].value = ONSITE_Q.options[action_choice]
    return plan


def test_a_required_radio_group_is_sent_to_the_model_as_a_choice():
    action = map_field(ONSITE_Q, PROFILE, "cv.pdf")
    assert action.needs_ai is True
    assert action.field.options == ["Yes", "No"]


def test_an_unanswered_required_group_blocks_the_submit():
    plan = build_plan(PageObservation(fields=[ONSITE_Q]), PROFILE, "cv.pdf")
    assert plan.unmapped_required() == [
        "Are you comfortable working in an onsite setting?"]


def test_an_already_checked_group_counts_as_answered():
    answered = FieldObs(tag="input", type="radio", name="q", label="Onsite?",
                        required=True, options=["Yes", "No"], value="Yes", ref="0")
    assert build_plan(PageObservation(fields=[answered]),
                      PROFILE, "cv.pdf").unmapped_required() == []


# Как ИМЕННО нажимается кнопка — забота виджета `widgets/choice.py`: он находит
# группу тем же способом, что и скрапер, и пробует нативный клик, метку и
# `check(force=True)` по очереди. Прежние тесты проверяли здесь селектор, номер и
# флаг force — это была проверка механики, и она пережила саму механику: на живой
# форме Recruitee `check(force=True)` в HEADED Chrome до спрятанной кнопки не
# доходит (лид #418), хотя в headless проходит. Уроки про номер внутри группы, про
# запасной путь по ref и про спрятанную кнопку теперь закреплены в
# `tests/test_choice_widget.py`, на настоящей разметке и в настоящем браузере.
# Здесь остаётся то, за что отвечает `fill_fields`: с каким ответом он зовёт
# виджет и что делает с отказом.

def _spy_choice(monkeypatch):
    calls = []

    def fake(page, locator, value="", index=None):
        calls.append({"value": value, "index": index})
        return (True, "")

    # Подменяется `_pick_choice_reason`, а не `_pick_choice`: с 2026-08-29
    # `fill_fields` зовёт версию с причиной, и подмена старого имени просто
    # переставала действовать — тест уходил в настоящий виджет с фальшивым
    # локатором и падал на «'_Loc' object has no attribute 'evaluate'».
    monkeypatch.setattr(ea, "_pick_choice_reason", fake)
    return calls


def test_the_chosen_option_is_handed_to_the_widget(monkeypatch):
    calls = _spy_choice(monkeypatch)
    ea.fill_fields(_Page(), _plan_with(1))          # "No"
    assert calls == [{"value": "No", "index": 1}]


def test_the_first_option_is_handed_over_the_same_way(monkeypatch):
    calls = _spy_choice(monkeypatch)
    ea.fill_fields(_Page(), _plan_with(0))
    assert calls == [{"value": "Yes", "index": 0}]


def test_a_refused_required_choice_becomes_a_manual_apply(monkeypatch):
    """Виджет отвечает False, а не исключением. Молча пройти мимо нельзя:
    обязательный вопрос без ответа — это форма, которая не отправится, и лучше
    узнать об этом здесь, чем по «ВОЗМОЖНО, ЗАЯВКА УЖЕ УШЛА» после сабмита."""
    monkeypatch.setattr(ea, "_pick_choice_reason",
                        lambda *a, **k: (False, "страница ответ не засчитала"))
    with pytest.raises(ManualApplyRequired, match="не выбрался вариант"):
        ea.fill_fields(_Page(), _plan_with(1))


def test_a_refused_optional_choice_is_skipped(monkeypatch):
    optional = FieldObs(tag="input", type="radio", name="q", label="Newsletter?",
                        required=False, options=["Yes", "No"], ref="9")
    plan = ApplyPlan(actions=[FillAction(field=optional, choice_index=1, value="No")])
    monkeypatch.setattr(ea, "_pick_choice_reason",
                        lambda *a, **k: (False, "страница ответ не засчитала"))
    ea.fill_fields(_Page(), plan)          # не бросает


def test_a_yes_no_profile_question_still_answers_without_the_model():
    relocate = FieldObs(tag="input", type="radio", name="r",
                        label="Are you willing to relocate?", required=True,
                        options=["Yes", "No"], ref="0")
    action = map_field(relocate, PROFILE, "cv.pdf")
    assert action.needs_ai is False
    assert action.choice_index == 0          # profile says open_to_relocation


# --- checkboxes hidden behind styled labels ---------------------------------

def test_a_consent_checkbox_goes_through_the_widget_too(monkeypatch):
    """«I consent» на LinkedIn помечена `required=false` и требуется всё равно:
    галочка оставалась пустой, форма отвечала "Select checkbox to proceed", и шаг
    не продвигался (лид 126). Прячут её тем же приёмом, что и кнопки Recruitee,
    поэтому и ставится она тем же виджетом, а его отказ виден вслух."""
    consent = FieldObs(tag="input", type="checkbox", name="c", label="I consent",
                       required=False, ref="7")
    calls = _spy_choice(monkeypatch)
    plan = build_plan(PageObservation(fields=[consent]), PROFILE, "cv.pdf")
    assert plan.actions[0].value == "true"          # recognised as consent

    ea.fill_fields(_Page(), plan)
    assert calls == [{"value": "", "index": 0}]


def test_a_consent_the_widget_could_not_tick_is_not_passed_over(monkeypatch):
    consent = FieldObs(tag="input", type="checkbox", name="c", label="I consent",
                       required=False, ref="7")
    monkeypatch.setattr(ea, "_pick_choice_reason",
                        lambda *a, **k: (False, "страница ответ не засчитала"))
    plan = build_plan(PageObservation(fields=[consent]), PROFILE, "cv.pdf")
    with pytest.raises(ManualApplyRequired, match="не поставилась галочка"):
        ea.fill_fields(_Page(), plan)


def test_an_unrelated_checkbox_is_left_alone():
    """Only consent-shaped boxes get ticked; «Настройка оповещения» sits on the
    same screen and is none of our business."""
    other = FieldObs(tag="input", type="checkbox", name="n",
                     label="Настройка оповещения", required=False, ref="8")
    page = _Page()
    ea.fill_fields(page, build_plan(PageObservation(fields=[other]), PROFILE, "cv.pdf"))
    assert page.checked == []


# --- an unflagged radio group is still a question ----------------------------

def test_an_unrequired_radio_group_is_answered_anyway():
    """Ashby marks no radio group required, then refuses the submit for one. A
    group of labelled answers to one prompt is a question whatever the DOM says."""
    q = FieldObs(tag="input", type="radio", name="g", required=False, ref="0",
                 label="What is your level in English",
                 options=["Beginner", "Intermediate", "Fluent/Native"])
    assert map_field(q, PROFILE, "cv.pdf").needs_ai is True


def test_an_optional_select_is_still_left_alone():
    """The language picker was a <select>. Answering optional ones switched the
    whole LinkedIn account to Arabic — that lesson stays."""
    picker = FieldObs(tag="select", type="select-one", label="Выберите язык",
                      required=False, ref="0",
                      options=["العربية", "Русский (Russian)"], value="Русский (Russian)")
    assert map_field(picker, PROFILE, "cv.pdf").needs_ai is False


def test_a_personal_status_group_is_answered_prefer_not_to_say():
    """«Marital Status» is the same kind of question as gender, and the form
    carries "I prefer not to say" for exactly this reason."""
    q = FieldObs(tag="input", type="radio", name="m", required=False, ref="0",
                 label="Marital Status",
                 options=["Single", "Married", "I prefer not to say", "Married with kids"])
    action = map_field(q, PROFILE, "cv.pdf")

    assert action.source == "eeo"
    assert action.value == "I prefer not to say"
    assert action.needs_ai is False


# --- разметка формы сохраняется, когда вариант не выбрался -------------------
#
# Отказ «не выбрался вариант» пришёл пять раз за три прогона, диагностика сузила
# его до «страница клик получает и не засчитывает», а дальше без живой разметки
# хода нет. Достать её вручную нельзя: надёжно зайти в форму можно только так,
# как это делает канал, то есть рискуя отправить заявку. Значит разметка должна
# прийти сама, из настоящего прогона.

def test_a_refused_required_choice_saves_the_form(monkeypatch, tmp_path):
    from app import config

    monkeypatch.setattr(config, "APPLY_DEBUG_DIR", str(tmp_path))
    monkeypatch.setattr(ea, "_pick_choice_reason",
                        lambda *a, **k: (False, "страница ответ не засчитала"))

    class _ContentPage(_Page):
        def content(self):
            return "<html>форма</html>"

        def screenshot(self, path=None):
            pass

    with pytest.raises(ManualApplyRequired):
        ea.fill_fields(_ContentPage(), _plan_with(1))

    saved = sorted(p.name for p in tmp_path.iterdir())
    assert any(n.endswith(".html") for n in saved), saved
    # Имя говорит, на каком вопросе застряли, — иначе дампы затирают друг друга.
    assert any("onsite" in n for n in saved), saved


def test_an_optional_choice_that_was_skipped_saves_nothing(monkeypatch, tmp_path):
    """Дамп пишется только там, где иначе остаётся гадать."""
    from app import config
    from app.domain.page_observation import FieldObs

    monkeypatch.setattr(config, "APPLY_DEBUG_DIR", str(tmp_path))
    monkeypatch.setattr(ea, "_pick_choice_reason",
                        lambda *a, **k: (False, "страница ответ не засчитала"))
    optional = FieldObs(tag="input", type="radio", name="q", label="Newsletter?",
                        required=False, options=["Yes", "No"], ref="9")
    ea.fill_fields(_Page(), ApplyPlan(actions=[
        FillAction(field=optional, choice_index=1, value="No")]))

    assert list(tmp_path.iterdir()) == []


def test_a_broken_dump_never_breaks_the_apply(monkeypatch, tmp_path):
    """Диагностика не имеет права ронять отклик — падает молча."""
    from app import config

    monkeypatch.setattr(config, "APPLY_DEBUG_DIR", str(tmp_path))
    monkeypatch.setattr(ea, "_pick_choice_reason",
                        lambda *a, **k: (False, "страница ответ не засчитала"))

    class _NoContent(_Page):
        def content(self):
            raise RuntimeError("страница закрылась")

    with pytest.raises(ManualApplyRequired, match="не выбрался вариант"):
        ea.fill_fields(_NoContent(), _plan_with(1))
