"""Готовый ответ профиля, которого НЕТ среди вариантов поля.

Замер живьём 2026-08-27, вакансия TradingView на Teamtailor
(`tradingview.teamtailor.com/jobs/7111379-frontend-team-lead`, лента remocate,
60 карточек). Форма раскрывается, из двенадцати полей одиннадцать план
заполняет, а отправку держит одно:

    REQ checkbox label='Locations*Required'
        name='candidate[location_ids][]' opts=['Tbilisi', 'Limassol', 'Paphos']

Это НЕ галочка согласия и не одиночный чекбокс: под одним `name` их три, скрапер
собирает их в ОДИН вопрос с тремя вариантами, и ветка одиночного чекбокса
(«agree|consent|privacy|…») до него не доходит вовсе — там `not f.options`.

Ломалось выше: подпись «Locations*Required» ловит правило `location|where are
you`, резолвер отдаёт из профиля «Astana, Kazakhstan», среди вариантов такого
города нет, `_option_index_for` возвращает None — и поле уходило в `unmapped`.
Обязательное, значит `unmapped_required()` держал уже готовую анкету.

Правило, по которому это чинится, в файле уже записано дважды, и оба раза для
той же развилки:
* строкой выше, когда факта в профиле НЕТ вовсе: «Обязательное отдаём модели: у
  неё в руках резюме и профиль»;
* в `_load_combobox_options`, когда ответ не нашёлся в словаре виджета: «Готовый
  ответ, которого нет в списке, — это пустое поле. Пусть его выберет модель:
  варианты у неё теперь есть, а профиль про чужой словарь знать не обязан».

Знать БОЛЬШЕ (ответ есть, просто он не из этого списка) и делать МЕНЬШЕ (молчать
вместо вопроса модели) — расхождение, а не осторожность. Необязательное поле
по-прежнему остаётся нетронутым: цена ответа на чужой необязательный виджет
измерена 2026-07-29 (переключатель языка LinkedIn увёз аккаунт на арабский).
"""
from app.application.auto_apply import build_plan, map_field
from app.domain.apply_profile import ApplyProfile
from app.domain.page_observation import FieldObs, PageObservation

PROFILE = ApplyProfile(full_name="Bolatbek Yermekov", first_name="Bolatbek",
                       last_name="Yermekov", email="a@b.com",
                       city="Astana", country="Kazakhstan")

# Снято со страницы: обязательность написана в подписи, `required` в разметке
# у Teamtailor стоит у одного поля из двенадцати, и не у этого.
LOCATIONS = FieldObs(tag="input", type="checkbox", label="Locations*Required",
                     name="candidate[location_ids][]",
                     options=["Tbilisi", "Limassol", "Paphos"])


def test_required_choice_without_profile_option_goes_to_the_model():
    a = map_field(LOCATIONS, PROFILE, "cv.pdf")
    assert a.needs_ai, f"поле ушло в {a.source}, отправка встанет"
    assert a.source == "ai"
    # Ответ выбирает модель, а не профиль: «Astana, Kazakhstan» тут не вариант.
    assert a.value == ""
    assert a.choice_index is None


def test_optional_choice_without_profile_option_is_left_alone():
    """Необязательное поле — чужая настройка, отправку оно не держит."""
    optional = FieldObs(tag="input", type="select", label="Location",
                        name="loc", options=["Tbilisi", "Limassol"])
    a = map_field(optional, PROFILE, "cv.pdf")
    assert not a.needs_ai
    assert a.source == "unmapped"


def test_a_contact_that_is_not_on_the_list_still_stays_for_a_human():
    """У почты верное значение ровно одно, и списком его не выбирают.

    LinkedIn Easy Apply отдаёт «Email address» списком подтверждённых адресов
    аккаунта (замер 2026-07-29). Нет нашего среди них — значит верного варианта
    нет вовсе, и любой выбор уедет работодателю чужим контактом.
    """
    field = FieldObs(tag="select", type="select-one", label="Email address",
                     required=True,
                     options=["Select an option", "someone.else@corp.com"],
                     value="Select an option")
    a = map_field(field, PROFILE, "cv.pdf")
    assert a.source == "unmapped"
    assert not a.needs_ai


def test_profile_option_that_is_on_the_list_still_wins():
    """Модель зовут только когда ответа в списке нет — иначе отвечает профиль."""
    f = FieldObs(tag="select", type="select", label="Country*Required",
                 name="country", options=["Georgia", "Kazakhstan", "Cyprus"],
                 required=True)
    a = map_field(f, PROFILE, "cv.pdf")
    assert a.source == "profile"
    assert a.choice_index == 1
    assert a.value == "Kazakhstan"


def test_tradingview_form_is_ready_once_the_model_has_answered():
    """Вся форма целиком: держал её ровно этот чекбокс."""
    obs = PageObservation(
        url="https://tradingview.teamtailor.com/jobs/7111379-frontend-team-lead",
        fields=[
            FieldObs(tag="input", type="text", label="First name*Required",
                     name="candidate[first_name]"),
            FieldObs(tag="input", type="text", label="Last name*Required",
                     name="candidate[last_name]"),
            FieldObs(tag="input", type="email", label="Email*Required",
                     name="candidate[email]"),
            FieldObs(tag="input", type="text",
                     label="Where are you currently based?*Required",
                     name="candidate[answers_attributes][0][text]"),
            LOCATIONS,
            FieldObs(tag="input", type="file", label="Drop your file or upload, Upload CV",
                     name="", required=True),
        ])
    plan = build_plan(obs, PROFILE, "cv.pdf")
    # До ответа модели анкета не готова — и это правильно, поле обязательное.
    assert "Locations*Required" in plan.unmapped_required()
    # Но вопрос модели ЗАДАН: без этого он не попал бы в ai_fields и остался бы
    # без ответа навсегда.
    assert "Locations*Required" in [a.field.label for a in plan.ai_fields]
