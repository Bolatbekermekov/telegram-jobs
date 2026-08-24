"""Выпадающий список вузов и работодателей: берём из списка, а не упираемся.

Замер 2026-08-25 на форме Datadog (Greenhouse): поле «School*» ищет по серверу и
на «Astana IT University» отдаёт НОЛЬ вариантов — как и на «Nazarbayev», а на
«Kazakh» показывает семь других вузов. Нужного там нет и не будет: это
справочник Greenhouse, а не перечень всех вузов мира.

Такое поле держало всю заявку. Решение владельца профиля (2026-08-25): в
выпадающем списке про учёбу или работодателя указывать любой вариант ИЗ СПИСКА,
а своё писать там, где поле свободное.

Порядок попыток при этом не «любой попавшийся»: сначала настоящее значение,
потом «Other» — форма держит его ровно для случаев «моего тут нет», и это
единственный по-настоящему верный ответ, — и только если списка «Other» не
предлагает, берётся первый вариант.

Свободное поле правило не трогает вовсе: там пишется своё.
"""
import pytest

from app.application.auto_apply import build_plan
from app.domain.apply_profile import ApplyProfile
from app.domain.channel import ManualApplyRequired
from app.domain.page_observation import FieldObs, PageObservation
from app.infrastructure.channels import external_apply as ea

PROFILE = ApplyProfile(full_name="Bolatbek Yermekov", first_name="Bolatbek",
                       email="a@b.com", city="Astana")


class _Loc:
    def __init__(self, page, sel):
        self.page, self.sel, self.first = page, sel, self

    def count(self):
        return 1

    def fill(self, v, **kw):
        self.page.filled[self.sel] = v


class _Page:
    def __init__(self, fields):
        self._fields = list(fields)
        self.filled = {}

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, js, *a):
        return ea.observation_to_raw(PageObservation(url="https://ats/x",
                                                     fields=self._fields))

    def locator(self, sel):
        return _Loc(self, sel)


def _school(**kw):
    return FieldObs(tag="input", type="text", label="School*", required=True,
                    combobox=True, ref="0", **kw)


def _run(monkeypatch, field, accepts, options=()):
    """Прогнать заполнение; `accepts` — какие значения список принимает."""
    tried = []

    def fake_fill(page, locator, value, **kwargs):
        tried.append(value)
        return value in accepts

    monkeypatch.setattr(ea, "_fill_combobox", fake_fill)
    monkeypatch.setattr(ea, "_combobox_options", lambda *a, **k: list(options))
    plan = build_plan(PageObservation(fields=[field]), PROFILE, "cv.pdf")
    plan.actions[0].value = "Astana IT University"
    ea.fill_fields(_Page([field]), plan)
    return tried


def test_other_is_preferred_when_our_own_answer_is_not_in_the_list(monkeypatch):
    """«Other» стоит в списке впереди чужих названий, даже если в разметке он
    ниже: это единственный вариант, который не врёт о кандидате."""
    tried = _run(monkeypatch, _school(), accepts={"Other - Asia Pacific"},
                 options=["Harvard", "Other - Asia Pacific"])
    assert tried == ["Astana IT University", "Other", "Other - Asia Pacific"]


def test_any_option_from_the_list_when_there_is_no_other(monkeypatch):
    """Решение владельца профиля: пустое поле держит заявку, вариант из списка —
    нет. Когда «Other» форма не предлагает, берётся первый предложенный."""
    tried = _run(monkeypatch, _school(), accepts={"Harvard"},
                 options=["Harvard", "Yale"])
    assert tried == ["Astana IT University", "Other", "Harvard"]


def test_a_real_match_is_left_alone(monkeypatch):
    """Если вуз в списке есть, никакой подмены не происходит."""
    tried = _run(monkeypatch, _school(), accepts={"Astana IT University"},
                 options=["Astana IT University"])
    assert tried == ["Astana IT University"]


def test_a_question_that_is_not_about_school_or_employer_still_fails(monkeypatch):
    """Правило узкое: «любой вариант» годится для справочника вузов, но не для
    вопроса про визу или зарплату — там подмена это неправда о себе."""
    visa = FieldObs(tag="input", type="text", label="Do you require visa sponsorship?*",
                    required=True, combobox=True, ref="0")
    with pytest.raises(ManualApplyRequired, match="не выбрался вариант"):
        _run(monkeypatch, visa, accepts=set(), options=["Yes", "No"])


def test_a_free_text_school_field_keeps_the_real_answer(monkeypatch):
    """Не combobox — пишем своё, как и просили."""
    field = FieldObs(tag="input", type="text", label="School*", required=True, ref="0")
    monkeypatch.setattr(ea, "_fill_combobox", lambda *a, **k: pytest.fail("не combobox"))
    plan = build_plan(PageObservation(fields=[field]), PROFILE, "cv.pdf")
    plan.actions[0].value = "Astana IT University"
    page = _Page([field])
    ea.fill_fields(page, plan)
    assert page.filled['[data-af="0"]'] == "Astana IT University"


# --- какой именно «Other» ------------------------------------------------------
# Замер 2026-08-25: справочник Datadog на запрос «Other» отдаёт шесть вариантов —
# Africa, Asia Pacific, Europe, Middle East, North America, South America. Виджет
# брал первый подходящий, то есть «Other - Africa», и выпускник из Астаны получал
# в анкету Африку. Формально это «вариант из списка», но рядом лежит верный, и
# писать заведомо не тот регион незачем.
KZ = ApplyProfile(full_name="B", email="a@b.com", city="Astana", country="Kazakhstan")
REGIONS = ["Other - Africa", "Other - Asia Pacific", "Other - Europe",
           "Other - Middle East", "Other - North America", "Other - South America"]


def _run_regions(monkeypatch, profile, accepts):
    tried = []

    def fake_fill(page, locator, value, **kwargs):
        tried.append(value)
        return value in accepts

    monkeypatch.setattr(ea, "_fill_combobox", fake_fill)
    monkeypatch.setattr(ea, "_combobox_options", lambda *a, **k: list(REGIONS))
    field = _school()
    plan = build_plan(PageObservation(fields=[field]), PROFILE, "cv.pdf")
    plan.actions[0].value = "Astana IT University"
    ea.fill_fields(_Page([field]), plan, profile=profile)
    return tried




@pytest.mark.parametrize("country,expected", [
    ("Kazakhstan", "Other - Asia Pacific"),
    ("Germany", "Other - Europe"),
    ("United States", "Other - North America"),
    ("United Arab Emirates", "Other - Middle East"),
])
def test_the_region_follows_the_profile_country(monkeypatch, country, expected):
    profile = ApplyProfile(full_name="B", email="a@b.com", country=country)
    tried = _run_regions(monkeypatch, profile, accepts={expected})
    assert tried[-1] == expected


def test_without_a_country_the_first_option_is_still_taken(monkeypatch):
    """Без страны угадывать нечем — правило владельца профиля («любой вариант»)
    работает как прежде, а не блокирует заявку."""
    profile = ApplyProfile(full_name="B", email="a@b.com")
    tried = _run_regions(monkeypatch, profile, accepts={"Other - Africa"})
    assert tried[-1] == "Other - Africa"
