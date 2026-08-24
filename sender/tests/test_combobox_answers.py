"""Откуда берётся ОТВЕТ на выпадающий вопрос, когда словарь у формы свой.

Прогон 2026-08-25, headed, dry_run по четырём живым формам: Profitap и
BlueThrone заполнились целиком, а N26 и Datadog встали на одном поле каждая —
«Where are you currently based?*» получило из профиля «Astana, Kazakhstan», а
предлагает «Berlin / Vienna / Barcelona / Other»; «Start date month*» получило
«1 month» из срока выхода, а предлагает названия месяцев. Виджет отказался
правильно: соседний город и чужой месяц в анкете хуже честного ручного отклика.
Чинить надо ответ, а не нажатие — профиль про чужой словарь не знает, поэтому
список надо прочитать у КАЖДОГО выпадающего поля и не подошедший к нему готовый
ответ отдать модели вместе с вариантами.

Здесь проверяется только этот выбор. Как список открывается и как вариант
нажимается — забота `widgets/combobox.py`, и проверяется она там.
"""
from app.application.auto_apply import ApplyPlan, FillAction
from app.domain.page_observation import FieldObs
from app.infrastructure.channels import external_apply as ea


class _Loc:
    def __init__(self, page, sel):
        self.page, self.sel = page, sel
        self.first = self


class _Page:
    """Страница, которая только помнит, у какого поля открывали список."""

    def __init__(self, options=None, blow_up=()):
        self.options = options or {}          # ref -> варианты
        self.blow_up = set(blow_up)           # refs, на которых чтение падает
        self.opened = []                      # refs, у которых открывали меню
        self.filled = {}

    def locator(self, sel):
        return _Loc(self, sel)

    def wait_for_timeout(self, ms):
        pass


def _options_reader(page, locator, **kw):
    """Подмена `combobox_options`: список читается, поле не трогается."""
    ref = locator.sel.split('"')[1]
    page.opened.append(ref)
    if ref in page.blow_up:
        raise RuntimeError("меню не открылось")
    return list(page.options.get(ref, []))


def _load(page, plan, monkeypatch):
    monkeypatch.setattr(ea, "_combobox_options", _options_reader)
    ea._load_combobox_options(page, plan)


def _combo(ref, label, **kw):
    return FieldObs(tag="input", type="text", label=label, combobox=True,
                    ref=ref, **kw)


def _plan(*actions):
    return ApplyPlan(actions=list(actions))


MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


# --- список читается у каждого выпадающего поля -----------------------------

def test_a_ready_answer_gets_its_options_read_too(monkeypatch):
    """Раньше список читался только у полей, которые и так шли к модели, — и
    ровно поэтому «Start date month*» у Datadog осталось пустым: ответ у него
    БЫЛ, просто не из этого словаря."""
    f = _combo("9", "Start date month*", required=True)
    a = FillAction(field=f, value="1 month", source="profile")

    _load(_Page(options={"9": MONTHS}), _plan(a), monkeypatch)

    assert f.options == MONTHS


def test_an_answer_outside_the_list_goes_to_the_model_with_the_list(monkeypatch):
    """N26, «Where are you currently based?*»: профиль отвечает городом, форма
    предлагает четыре европейских офиса и «Other». Ответ надо выбрать заново, и
    выбрать его есть кому — но только если варианты дойдут до модели."""
    f = _combo("9", "Where are you currently based?*", required=True)
    a = FillAction(field=f, value="Astana, Kazakhstan", source="profile")

    _load(_Page(options={"9": ["Berlin", "Vienna", "Barcelona", "Other"]}),
          _plan(a), monkeypatch)

    assert a.needs_ai and a.source == "ai"
    assert a.value == "" and a.choice_index is None
    assert f.options == ["Berlin", "Vienna", "Barcelona", "Other"]


def test_an_answer_the_list_carries_stays_as_the_profile_wrote_it(monkeypatch):
    """«Country*» у Greenhouse называет Казахстан «Kazakhstan +7» — в тексте
    варианта телефонный код. Это тот же ответ, и звать из-за него модель незачем."""
    f = _combo("3", "Country*", required=True)
    a = FillAction(field=f, value="Kazakhstan", source="profile")

    _load(_Page(options={"3": ["Japan +81", "Kazakhstan +7", "Kenya +254"]}),
          _plan(a), monkeypatch)

    assert not a.needs_ai and a.value == "Kazakhstan" and a.source == "profile"


def test_no_on_a_list_of_months_is_not_november(monkeypatch):
    """Сверять ответ со списком подстрокой в обе стороны нельзя: «No» лежит
    внутри «November», и такой ответ на вопрос с месяцами считался бы совпавшим,
    оставался бы у поля — а виджет, у которого сверка по границе слова, ноября
    всё равно не выберет, и обязательное поле уйдёт в ручной отклик.

    Решать должна ровно та функция, которая будет нажимать: `widgets.combobox`.
    """
    f = _combo("9", "Start date month*", required=True)
    a = FillAction(field=f, value="No", source="profile")

    _load(_Page(options={"9": MONTHS}), _plan(a), monkeypatch)

    assert a.needs_ai, "«No» не выбирает ноябрь — вопрос должен уйти к модели"


# --- меню открывается только там, где без него не обойтись ------------------

def test_a_field_that_is_not_a_combobox_is_left_alone(monkeypatch):
    """Открытие меню стоит 0,65–1,74 с на поле (замер 2026-08-25 на живых
    формах): на анкете Datadog из 25 выпадающих это 20 секунд, и тратить их на
    поля, у которых меню нет вовсе, незачем."""
    plain = FieldObs(tag="input", type="text", label="First name", ref="0")
    page = _Page()

    _load(page, _plan(FillAction(field=plain, value="Bolatbek", source="profile")),
          monkeypatch)

    assert page.opened == []


def test_a_select_that_already_listed_its_options_is_not_opened(monkeypatch):
    f = _combo("2", "Degree*", required=True, options=["Bachelor's Degree", "Other"])
    page = _Page(options={"2": ["что-то другое"]})

    _load(page, _plan(FillAction(field=f, needs_ai=True, source="ai")), monkeypatch)

    assert page.opened == []
    assert f.options == ["Bachelor's Degree", "Other"]


def test_a_field_nobody_is_going_to_fill_is_not_opened(monkeypatch):
    """Необязательный вопрос, на который нет ни ответа из профиля, ни задания
    модели, останется пустым в любом случае — открывать его меню незачем.
    Замер 2026-08-25: у Datadog это «Are you Hispanic/Latino?»."""
    f = _combo("34", "Are you Hispanic/Latino?")
    page = _Page(options={"34": ["Yes", "No", "Decline To Self Identify"]})

    _load(page, _plan(FillAction(field=f, source="unmapped")), monkeypatch)

    assert page.opened == []


def test_reading_the_list_never_fills_the_field(monkeypatch):
    """Читаем список — и только. Поле, заполненное «на посмотреть», это чужой
    ответ в анкете."""
    f = _combo("9", "Start date month*", required=True)
    page = _Page(options={"9": MONTHS})

    _load(page, _plan(FillAction(field=f, value="1 month", source="profile")),
          monkeypatch)

    assert page.filled == {}


# --- список, который не является словарём поля ------------------------------

def test_a_server_page_of_options_is_not_taken_for_the_whole_vocabulary(monkeypatch):
    """«School*» у Datadog отдаёт при открытии РОВНО 100 вузов по алфавиту, от
    «3iL Limoges»: это страница ответа сервера, а не список того, что поле
    принимает — остальное приходит по мере ввода. Замер 2026-08-25.

    Выдать такую сотню за словарь значит заставить модель выбирать чужой вуз:
    ответ на вопрос с вариантами клампится в индекс, «не знаю» там нет. Пусть
    вопрос останется свободным — модель ответит по резюме, а нужный вариант
    найдёт виджет, он умеет печатать и ждать ответа сервера.
    """
    f = _combo("7", "School*", required=True)
    page = _Page(options={"7": [f"University {i}" for i in range(100)]})
    a = FillAction(field=f, needs_ai=True, source="ai")

    _load(page, _plan(a), monkeypatch)

    assert f.options == [], "сотня вариантов — страница, а не словарь"
    assert a.needs_ai and a.source == "ai"


def test_a_list_that_is_empty_until_you_type_leaves_the_answer_alone(monkeypatch):
    """«Location (City)*» у N26 при открытии не предлагает НИЧЕГО — варианты
    приходят с сервера на введённое. Ответ «Astana» тут верный, и стереть его
    из-за пустого списка значит сломать поле, которое работает."""
    f = _combo("5", "Location (City)*", required=True)
    a = FillAction(field=f, value="Astana", source="profile")

    _load(_Page(options={"5": []}), _plan(a), monkeypatch)

    assert a.value == "Astana" and not a.needs_ai


# --- поля о происхождении, поле и здоровье ----------------------------------

def test_an_eeo_question_is_declined_by_rule_not_guessed_by_the_model(monkeypatch):
    """«Prefer not to say» — не догадка профиля, а решение не отвечать, и в
    списке оно называется иначе: у Datadog это «Decline To Self Identify».
    Отправить такой вопрос модели значит попросить её ответить по существу, чего
    никто не просил: резюме она читала. Выбираем то же, что выбрал бы map_field,
    знай он варианты при разборе формы."""
    f = _combo("33", "Gender")
    a = FillAction(field=f, value="Prefer not to say", source="eeo")

    _load(_Page(options={"33": ["Male", "Female", "Decline To Self Identify"]}),
          _plan(a), monkeypatch)

    assert not a.needs_ai
    assert a.value == "Decline To Self Identify" and a.choice_index == 2


def test_an_eeo_list_without_a_decline_option_falls_back_to_the_last_one(monkeypatch):
    """Ровно правило map_field: «Veteran Status» у Datadog предлагает «I don't
    wish to answer», где нет ни «decline», ни «prefer not» — но стоит оно
    последним, как и заведено на таких списках."""
    f = _combo("35", "Veteran Status")
    opts = ["I am not a protected veteran",
            "I identify as one or more of the classifications of a protected veteran",
            "I don't wish to answer"]
    a = FillAction(field=f, value="Prefer not to say", source="eeo")

    _load(_Page(options={"35": opts}), _plan(a), monkeypatch)

    assert a.value == "I don't wish to answer" and not a.needs_ai


# --- сбой чтения не должен стоить отклика -----------------------------------

def test_a_menu_that_would_not_open_leaves_everything_as_it_was(monkeypatch):
    """Чужой виджет вправе повести себя как угодно. Не прочитали список — идём
    дальше ровно с тем, что было: так работало до этой правки, и терять из-за
    одного упрямого поля целую заявку незачем."""
    bad = _combo("1", "Where are you currently based?*", required=True)
    good = _combo("2", "Start date month*", required=True)
    a_bad = FillAction(field=bad, value="Astana, Kazakhstan", source="profile")
    a_good = FillAction(field=good, value="1 month", source="profile")

    _load(_Page(options={"2": MONTHS}, blow_up={"1"}),
          _plan(a_bad, a_good), monkeypatch)

    assert a_bad.value == "Astana, Kazakhstan" and not a_bad.needs_ai
    assert a_good.needs_ai, "соседнее поле разбирается как ни в чём не бывало"
