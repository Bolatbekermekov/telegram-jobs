"""Обязательность, написанная в ПОДПИСИ, когда в DOM её нет.

Замер живых форм 2026-08-24/25 тем же скрейпером, что работает в проде
(`_SCRAPE_JS` из external_apply): Teamtailor (careers.bluethrone.io, вакансия
8175038) отдаёт 19 полей и ровно ОДНО с `required=true` — у остальных
обязательность написана словами прямо в подписи. Personio (вакансии 1245032 у
synaforce-gmbh.jobs.personio.de и 2673489 у prologistik-group.jobs.personio.com)
и Zalando (jobs.zalando.com, вакансия 2723788) — ни одного `required=true` на
всю форму.

Что ловят эти тесты: `unmapped_required()` — последний заслон перед необратимым
Submit — верил DOM на слово, поэтому на таких формах не удерживал НИЧЕГО, и
анкета уходила работодателю с пустыми обязательными полями.

Обратная сторона так же дорога: лишнее «обязательное» поле утащит в ручной
отклик заявку, которая ушла бы сама, — поэтому половина тестов здесь про то, что
правило НЕ срабатывает.
"""
from app.application.auto_apply import (
    build_plan, field_is_required, label_says_required, map_field,
)
from app.domain.apply_profile import ApplyProfile
from app.domain.page_observation import FieldObs, PageObservation

PROF = ApplyProfile(
    full_name="Bolatbek Yermekov", first_name="Bolatbek", last_name="Yermekov",
    email="a@b.com", phone="+7 775 720 0604", city="Astana", country="Kazakhstan",
    linkedin="https://linkedin.com/in/x", github="https://github.com/x",
    needs_visa_sponsorship=False, open_to_relocation=True,
    desired_salary="$70,000/year", notice_period="2 weeks",
)
CV = "C:/cv.pdf"


# Подписи ниже скопированы из замера как есть, включая обрезку до 80 символов,
# которую делает сам скрейпер (`norm`), и «мусорный хвост» соседнего элемента,
# приклеенный innerText-ом («Attach File», «ATTACH RESUME/CV…»).
MARKED = [
    # Teamtailor, careers.bluethrone.io: <sup>*</sup><span>Required</span>.
    "What's your LinkedIn?*Required",
    "Where are you currently based?*Required",
    "Locations*Required",
    "First name*Required",
    "Email*Required",
    "How many years of production Go experience do you have?*Required",
    "Which of the following employment methods would you be open to?*Required 🔴 Plea",
    # Teamtailor, галочка согласия: «Required.» стоит ПЕРЕД текстом, а звёздочка
    # в конце предложения — за 80-м символом, её обрезает скрейпер.
    "Required.By submitting this application, I agree that I have read the Privacy Po",
    # Zalando, jobs.zalando.com: звёздочка вплотную к подписи, иногда с
    # приклеенным текстом соседней кнопки.
    "First Name*",
    "Country Code*",
    "Résume*Attach File",
    "Are you employed by any of Zalando entities?*",
    "I identify as*",
    # Greenhouse, job-boards.greenhouse.io/customerio/jobs/7778289 — здесь DOM
    # обязательность проставляет, но подпись говорит то же самое.
    "Country*",
    "Have you previously been employed with Customer.io? *",
    # Lever, jobs.lever.co: ✱ (U+2731), а не обычная звёздочка.
    "Full name✱",
    "Email✱",
    "Resume/CV ✱ATTACH RESUME/CVCouldn't auto-read resume.Analyzing resume...Success!",
    # Personio, немецкие формы: «* (erforderlich)».
    "E-Mail* (erforderlich)",
    "Verfügbar ab* (erforderlich)",
    "Wie bist du auf uns aufmerksam geworden?* (erforderlich)",
    "Liegt dein Wohnort in Deutschland, in Österreich oder in der Schweiz?* (erforder",
]

UNMARKED = [
    # Сноска формы. Снята живьём с Greenhouse (customer.io): отдельный <p>,
    # внутри «*» и «indicates a required field». Ни подписи перед звёздочкой, ни
    # заглавной буквы после — это не маркер, а легенда ко всей форме.
    "* indicates a required field",
    "Fields marked with * are required",
    # Слово «required» в смысле «требуется опыт». Первая строка — проза со
    # страницы Greenhouse (PUBLIC BURDEN STATEMENT), остальные — та же форма.
    "no persons are required to respond to a collection of information unless",
    "5+ years of production Go experience required",
    "Bachelor degree required",
    # Lever: «requirement», а не «required» — слово другое, и поле необязательное.
    "Our contracts have a residency requirement of living in the United States for th",
    # Звёздочка-сноска посреди фразы: за ней предложение продолжается строчной
    # буквой, то есть это часть текста, а не пометка к подписи.
    "We offer a competitive salary* and equity",
    "I agree to the terms. Marketing emails may follow* Unsubscribe anytime",
    # Звёздочки как украшение и как разделитель: пометка обязательности всегда
    # одиночная.
    "*** IMPORTANT *** Read before applying",
    "* * *",
    # Настоящие НЕОБЯЗАТЕЛЬНЫЕ поля тех же самых форм.
    "LinkedIn profile (optional)",                 # Paysenger
    "Yes, BlueThrone can contact me directly about specific future job opportunities.",
    "(Optional) Add a cover letter or anything else you would like to share",  # Ashby
    "Vorname", "Telefon", "Gehaltsvorstellung",    # Personio
    "Phone number with country code",              # Teamtailor
    "GitHub", "Cover Letter", "How did you hear about this job?",
]


def test_label_marker_is_read_as_required():
    """Подпись говорит «обязательно», DOM молчит — верить надо подписи."""
    for label in MARKED:
        assert label_says_required(label) is True, label
        assert field_is_required(
            FieldObs(tag="input", type="text", label=label, required=False)) is True, label


def test_prose_that_only_looks_like_a_marker_is_not_required():
    """Обратная цена: лишнее «обязательное» уводит в ручной отклик заявку,
    которая ушла бы сама. Ни сноска «* indicates a required field», ни «5+ years
    required», ни звёздочка посреди фразы маркером не считаются."""
    for label in UNMARKED:
        assert label_says_required(label) is False, label
        assert field_is_required(
            FieldObs(tag="input", type="text", label=label, required=False)) is False, label


def test_dom_flag_still_wins_when_the_label_says_nothing():
    """Правило только ДОБАВЛЯЕТ обязательность, снять её оно не может."""
    assert field_is_required(
        FieldObs(tag="input", type="file", label="Upload CV", required=True)) is True


def test_personio_form_holds_the_submit_instead_of_going_out_half_empty():
    """Живой замер 2026-08-25, prologistik-group.jobs.personio.com/job/2673489:
    ни одного `required=true` на всю форму. До правила `unmapped_required()`
    возвращал пустой список, `ready_to_submit()` — True, и анкета уходила без
    «Verfügbar ab» и «Ort», которые Personio требует."""
    obs = PageObservation(fields=[
        FieldObs(tag="input", type="text", label="Vorname", required=False),
        FieldObs(tag="input", type="email", label="E-Mail* (erforderlich)", required=False),
        FieldObs(tag="input", type="text", label="Telefon", required=False),
        FieldObs(tag="input", type="text", label="Verfügbar ab* (erforderlich)",
                 required=False),
        FieldObs(tag="input", type="text", label="Gehaltsvorstellung", required=False),
    ])
    plan = build_plan(obs, PROF, CV)
    held = plan.unmapped_required()
    assert "Verfügbar ab* (erforderlich)" in held
    assert plan.ready_to_submit() is False
    # Необязательные полями-заложниками не становятся: иначе в ручной отклик
    # уехала бы вся форма целиком.
    assert not any("Vorname" in h or "Telefon" in h or "Gehaltsvorstellung" in h
                   for h in held)
    # Почту заполнил профиль — маркер её в заложники не берёт.
    assert not any("E-Mail" in h for h in held)


def test_a_field_marked_only_in_the_label_is_answered_by_the_model():
    """Признать поле обязательным мало: если его при этом не заполнять, каждая
    такая форма уходит в manual. Незнакомое обязательное поле идёт к модели —
    ровно как поле с `required=true` в DOM."""
    a = map_field(FieldObs(tag="input", type="text",
                           label="Verfügbar ab* (erforderlich)"), PROF, CV)
    assert a.needs_ai is True and a.source == "ai"


def test_a_select_marked_only_in_the_label_is_answered_too():
    """Незнакомый выпадающий список отвечается ТОЛЬКО когда форма его требует —
    цена ответа на чужой необязательный виджет измерена (переключатель языка
    LinkedIn увёз аккаунт на арабский 2026-07-29). Маркер в подписи — это и есть
    «форма требует»: Personio рисует «Wie stufst du dein deutsches Sprachniveau
    ein?* (erforderlich)» без единого `required` в DOM."""
    marked = map_field(FieldObs(
        tag="select", type="select-one",
        label="Wie stufst du dein deutsches Sprachniveau ein?* (erforderlich)",
        options=["", "Muttersprache", "C1", "B2"]), PROF, CV)
    assert marked.needs_ai is True
    plain = map_field(FieldObs(tag="select", type="select-one", label="Sprache",
                               options=["Deutsch", "English"]), PROF, CV)
    assert plain.needs_ai is False and plain.source == "unmapped"


def test_teamtailor_consent_marked_by_the_word_is_ticked_not_held():
    """«Required.By submitting this application, I agree …» — галочка согласия
    Teamtailor. Она обязательная, но держать из-за неё отправку не надо: её
    ставит правило согласия, и форма уходит."""
    obs = PageObservation(fields=[
        FieldObs(tag="input", type="checkbox", required=False,
                 label="Required.By submitting this application, I agree that I have "
                       "read the Privacy Po"),
    ])
    plan = build_plan(obs, PROF, CV)
    assert plan.actions[0].value == "true" and plan.actions[0].source == "profile"
    assert plan.ready_to_submit() is True
