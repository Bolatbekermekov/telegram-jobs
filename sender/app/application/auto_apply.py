"""Pure mapping: form fields + ApplyProfile -> concrete fill actions.

Deterministic facts come from the profile; free-text questions are flagged
needs_ai for a later, injected answerer (see answer_ai_fields, added next).
No Playwright, no network — fully testable.
"""
import re
from dataclasses import dataclass, field
from datetime import date

from app.domain.apply_profile import ApplyProfile, work_authorized_in
from app.domain.availability import availability_iso, notice_option_index, notice_period_in
from app.domain.birth_date import (
    age_on, asks_age, asks_date_of_birth, birth_date_text, minimum_age_asked,
)
from app.domain.date_format import date_for_field, looks_like_date_pattern
from app.domain.page_observation import FieldObs, PageObservation

EEO_ANSWER = "Prefer not to say"

_SKIP_FILL_RE = re.compile(r"cookie|newsletter|subscrib|\bsearch\b", re.I)

# Longest a label can be and still be treated as a field caption. Beyond this it
# reads as a question (or as prose smuggling keywords), so keyword rules stop
# applying — see map_field. "Are you legally authorized to work in the US?" is 46.
_MAX_LABEL_CHARS = 80

# Подпись поля-даты, которое спрашивает про НАШ выход на работу. «graduation
# date», «End date» и даты прошлых мест сюда намеренно не попадают: у Greenhouse
# раздел образования подписан «Start date month» / «Start date year», и прежнее
# правило подставляло туда срок отработки — форма Datadog отклонила отправку с
# «Start date year*» (замер 2026-08-26).
_AVAILABILITY_DATE_RE = re.compile(
    r"availab|available start|start date|starting date|joining|can you start|"
    # «When is the earliest you would want to start at …?» (Ashby, 2026-09-13).
    r"earliest\b.{0,40}\bstart|want to start|"
    # «What is your last working date?» (Indeed Apply, #1228, 2026-09-14) —
    # последний день на нынешней работе, то есть конец срока отработки.
    r"last working (?:date|day)|last day (?:at|of|in) (?:your )?(?:current|present)|"
    r"notice period|дата выхода|когда.*готов", re.IGNORECASE)

# Вопрос про срок отработки — без требования даты. Отдельно от
# `_AVAILABILITY_DATE_RE`: тот про контрол-календарь, этот про число в
# названных единицах.
_NOTICE_RE = re.compile(r"notice period|срок отработки", re.IGNORECASE)

# `ctc\b` без левой границы намеренно: ECTC (expected) и CCTC (current) — это
# тот же CTC с приставкой, и «\bctc\b» не поймал бы ни одного.
_SALARY_Q_RE = re.compile(r"salary|compensation|ctc\b|expected pay|\brate\b", re.I)
_CURRENT_SALARY_RE = re.compile(r"\bcurrent\b|\bcctc\b|текущ", re.I)
_POSTAL_RE = re.compile(r"postal|\bzip\b|zip\s?code|post\s?code|почтов\w*\s+индекс|\bиндекс\b",
                        re.I)
# Не «email address» и не «web address» — только адрес проживания.
_STREET_RE = re.compile(
    r"street|address\s*line|(?:home|mailing|residential)\s+address|улица|адрес\s+проживания",
    re.I)

# label/name regex -> resolver(profile) -> value ("" means "no fact, skip rule").
_LABEL_RULES = [
    (re.compile(r"e-?mail", re.I), lambda p: p.email),
    # «Contact Number» и WhatsApp — тоже телефон (живьём 2026-09-13, лид #1163:
    # поле ушло модели, та подставила номер, и защита личных данных остановила
    # отклик). Телефон — факт профиля, а не ответ модели.
    (re.compile(r"phone|mobile|\btel\b|телефон|whats\s?app|contact\s*(?:number|no\b)", re.I),
     lambda p: p.phone),
    (re.compile(r"first name|given name", re.I), lambda p: p.first_name),
    (re.compile(r"last name|surname|family name", re.I), lambda p: p.last_name),
    (re.compile(r"full name|your name|\bname\b", re.I), lambda p: p.full_name),
    (re.compile(r"linkedin", re.I), lambda p: p.linkedin),
    (re.compile(r"telegram|телеграм|\btg\b", re.I), lambda p: p.telegram),
    (re.compile(r"github", re.I), lambda p: p.github),
    (re.compile(r"portfolio|personal website|website|\burl\b", re.I), lambda p: p.portfolio),
    (re.compile(r"\bcity\b|town", re.I), lambda p: p.city),
    (re.compile(r"country", re.I), lambda p: p.country),
    (re.compile(r"location|where are you", re.I),
     lambda p: ", ".join(x for x in (p.city, p.country) if x)),
    (re.compile(r"salary|compensation|expected pay|\brate\b", re.I), lambda p: p.desired_salary),
    (re.compile(r"notice period|availability", re.I), lambda p: p.notice_period),
]

# Правила выше, у которых верное значение РОВНО ОДНО: это способ работодателя с
# нами связаться и наше имя. Если такого значения нет среди вариантов поля, то
# верного варианта там нет вовсе, и выбрать любой — значит сообщить чужой
# контакт. Такое поле остаётся человеку.
#
# Замер 2026-07-29, LinkedIn Easy Apply: «Email address» приходит выпадающим
# списком ПОДТВЕРЖДЁННЫХ адресов аккаунта, и адреса из профиля среди них может
# не быть (см. test_prefilled_fields).
#
# Остальное в списке — место, страна, срок выхода — вопросы ВЫБОРА: набор
# ответов задаёт сам работодатель («Locations*Required»: Tbilisi / Limassol /
# Paphos), и профиль про этот набор знать не обязан.
#
# Подписи взяты у самих правил, а не написаны заново: «\bname\b» покрывает
# first/last/full/given/family name, «surname» словом не режется.
_ONE_TRUE_VALUE_RE = re.compile(
    r"e-?mail|phone|mobile|\btel\b|телефон|whats\s?app|contact\s*(?:number|no\b)|"
    r"\bname\b|surname|linkedin|telegram|телеграм|"
    r"\btg\b|github|portfolio|personal website|website|\burl\b", re.I)


@dataclass
class FillAction:
    field: FieldObs
    value: str = ""                 # text value, file path, or chosen option text
    choice_index: int | None = None
    is_file: bool = False
    needs_ai: bool = False
    source: str = "unmapped"        # profile | cv | eeo | custom | ai | unmapped


# A select's "nothing chosen yet" option. Its text is what the scraper reports as
# the field's current value, so without this list an untouched dropdown would read
# as already answered.
_PLACEHOLDER_OPTION_RE = re.compile(
    r"^(select(\s+an?\s+\w+)?|please select|choose(\s+\w+)?|"
    r"выбер(и|ите)[^|]*|выбрать|не выбрано|[-—–])\.{0,3}$", re.IGNORECASE)


# ── Обязательность, написанная в ПОДПИСИ ─────────────────────────────────────
#
# Замер живых форм 2026-08-24/25 тем же скрейпером, что работает в проде:
#   Teamtailor (careers.bluethrone.io, вакансия 8175038) — 19 полей, `required`
#     ровно у ОДНОГО («Upload CV»). У остальных обязательность написана словами
#     прямо в подписи: «First name*Required», «Locations*Required»,
#     «What's your LinkedIn?*Required».
#   Personio (synaforce-gmbh.jobs.personio.de/job/1245032 и
#     prologistik-group.jobs.personio.com/job/2673489) — ни одного `required` на
#     всю форму, маркер «E-Mail* (erforderlich)», «Verfügbar ab* (erforderlich)».
#   Zalando (jobs.zalando.com, вакансия 2723788) — ни одного `required`, маркер
#     «First Name*», «Résume*Attach File», «I identify as*».
#   Lever (jobs.lever.co) — «Full name✱», «Email✱» (это U+2731, не звёздочка). У
#     вакансии, где резюме обязательно, подпись «Resume/CV ✱ATTACH RESUME/CV…», а
#     где нет — та же подпись без ✱. Маркер и есть единственная разница.
#
# Пока верили `required` на слово, `unmapped_required()` на таких формах не
# удерживал НИЧЕГО, и анкета уходила работодателю с пустыми обязательными полями.
#
# Цена ошибки в другую сторону не меньше: лишнее «обязательное» поле утащит в
# ручной отклик заявку, которая ушла бы сама. Поэтому маркером считается не
# всякая звёздочка и не всякое слово «required», а только то, что стоит НА МЕСТЕ
# пометки — вплотную за концом подписи:
#   * перед маркером должна быть сама подпись. Сноска «* indicates a required
#     field» (снята живьём с Greenhouse, отдельный <p> над формой) начинается со
#     звёздочки — это легенда ко всей форме, а не пометка к полю;
#   * за маркером фраза не продолжается строчной буквой: «competitive salary* and
#     equity» — сноска в прозе;
#   * до маркера в подписи нет законченного предложения — звёздочка в глубине
#     длинного текста согласия относится не к подписи.
# Слово «required» само по себе маркером не считается вовсе: «5+ years required»
# и «Bachelor degree required» — про опыт, а не про поле, и «requirement» из
# живого вопроса Lever («a residency requirement of living in the United
# States») это не «required». Слово читается только на месте пометки:
# приклеенным к звёздочке («Locations*Required»), в скобках сразу за ней
# («* (erforderlich)») или отдельным словом в начале подписи с точкой
# («Required.By submitting this application…» — та же Teamtailor, где звёздочку
# в конце предложения срезает обрезка подписи до _MAX_LABEL_CHARS).
#
# Обрезка вообще стоит дорого: у той же Teamtailor «…without needing visa
# sponsorship?*Required» теряет маркер вместе с хвостом, и такое поле мы
# по-прежнему не удержим. Пропустить обязательное поле — прежнее поведение;
# придумать обязательность там, где её нет, — новый ущерб. Правило ошибается
# в первую сторону намеренно.
#
# Проверка на всём замере: 144 поля с девяти живых форм (Teamtailor, Zalando,
# Paysenger, Greenhouse, Lever ×2, Personio ×2, Ashby), правило срабатывает на
# 40 — и все сорок несут маркер в подписи буквально. Ни одного срабатывания на
# прозе: ни на согласии Zalando про чувствительные данные, ни на абзаце Ashby
# про SMS, ни на «(Optional) Add a cover letter», ни на сноске Greenhouse.
_STAR_RE = re.compile(r"[*✱＊]")
# Языки, снятые живьём: EN («Required») и DE («erforderlich», по корню — конец
# слова обрезка съедает: «…Schweiz?* (erforder»). RU добавлен тем же образцом.
_REQUIRED_WORD = r"required|erforder\w*|pflichtfeld|обязательн\w*"
# Чем кончается подпись, к которой пометку можно приклеить.
_CAPTION_TAIL_RE = re.compile(r"[\w)\]?!:»\"']$")
# Законченное предложение до маркера: значит, он стоит уже не при подписи.
_SENTENCE_BREAK_RE = re.compile(r"[.!?]\s+[A-ZА-ЯЁ]")
# Фраза продолжается — звёздочка была сноской. Скобку пропускаем: «* (примерно)»
# это тоже продолжение, а «* (erforderlich)» ловится словом-пометкой ниже.
_TAIL_CONTINUES_RE = re.compile(r"^\s*[(\[]?\s*[a-zа-яё]")
_TAIL_IS_REQUIRED_WORD_RE = re.compile(
    r"^\s*[(\[]?\s*(?:" + _REQUIRED_WORD + r")", re.I)
_LEADING_REQUIRED_RE = re.compile(r"^\s*(?:" + _REQUIRED_WORD + r")\s*[.:*]", re.I)


def label_says_required(label: str) -> bool:
    """Несёт ли ПОДПИСЬ поля пометку обязательности — см. разбор выше."""
    text = (label or "").strip()
    if not text:
        return False
    if _LEADING_REQUIRED_RE.match(text):
        return True
    # Звёздочек может быть несколько (сноска формы плюс пометка поля), поэтому
    # каждая проверяется отдельно: хватит одной, стоящей на месте пометки.
    for m in _STAR_RE.finditer(text):
        head, tail = text[:m.start()].rstrip(), text[m.end():]
        # Ряд звёздочек — украшение или разделитель («*** ВАЖНО ***»), а пометка
        # обязательности всегда одиночная.
        if _STAR_RE.match(text[m.start() - 1:m.start()]) or _STAR_RE.match(tail[:1]):
            continue
        if not _CAPTION_TAIL_RE.search(head) or _SENTENCE_BREAK_RE.search(head):
            continue
        if not tail.strip() or _TAIL_IS_REQUIRED_WORD_RE.match(tail):
            return True
        if not _TAIL_CONTINUES_RE.match(tail):
            return True
    return False


def field_is_required(f: FieldObs) -> bool:
    """Обязательное поле — по DOM ИЛИ по подписи.

    Правило только ДОБАВЛЯЕТ обязательность: `required=true` в разметке остаётся
    решающим, снять его подпись не может.
    """
    return bool(f.required) or label_says_required(f.label)


def _satisfied(a: FillAction) -> bool:
    if a.is_file:
        return bool(a.value)
    if a.choice_index is not None:
        return True
    if a.value.strip() and "[" not in a.value:
        return True
    # Nothing planned for it, but the page already carries an answer. Measured on
    # LinkedIn Easy Apply (2026-07-29): the form arrives with the account's email
    # and «Phone country code» already selected, and neither can be matched from
    # the profile — the account email need not be the profile one, and a code like
    # "Kazakhstan (+7)" is not a phone number. Treating those as unfilled is what
    # made every Easy Apply job unreachable.
    return already_answered(a.field)


def already_answered(f: FieldObs) -> bool:
    """Поле уже держит ответ страницы: не пустое и не «Select an option»."""
    current = (f.value or "").strip()
    return bool(current) and not _PLACEHOLDER_OPTION_RE.match(current)


@dataclass
class ApplyPlan:
    actions: list[FillAction] = field(default_factory=list)

    @property
    def ai_fields(self) -> list[FillAction]:
        return [a for a in self.actions if a.needs_ai]

    def unmapped_required(self) -> list[str]:
        # Последний заслон перед необратимой отправкой, поэтому обязательность
        # берётся не только из разметки: половина ATS её там просто не ставит.
        return [a.field.label or a.field.name
                for a in self.actions if field_is_required(a.field) and not _satisfied(a)]

    def ready_to_submit(self) -> bool:
        return not self.unmapped_required()


def is_fillable_field(f: FieldObs) -> bool:
    """Wider than classify.is_real_field: keep consent/agreement checkboxes (we may
    need to tick them), drop only cookie-banner/newsletter/search noise."""
    if f.type in ("hidden", "submit", "button", "reset", "image"):
        return False
    if _SKIP_FILL_RE.search(f"{f.label} {f.name}"):
        return False
    return True


def _match_choice(options: list[str], *wants: str) -> int | None:
    for i, opt in enumerate(options):
        low = opt.lower()
        if any(w in low for w in wants):
            return i
    return None


# Подпись поля, которое просит СОПРОВОДИТЕЛЬНОЕ ПИСЬМО, на языках стран, по
# которым мы ищем. Замер 2026-08-03: «Anschreiben» (стандартное немецкое слово),
# «List motywacyjny», «Lettera di presentazione» и «Carta de presentación»
# получали РЕЗЮМЕ вместо письма — работодателю уходил не тот документ, и
# заметить это было некому. Германия, Польша и Италия входят в SEARCH_LOCATIONS.
COVER_LETTER_RE = re.compile(
    r"cover\s*letter|motivation(al)?\s*letter|letter\s+of\s+motivation|"
    r"anschreiben|motivationsschreiben|"          # DE
    r"lettre\s+de\s+motivation|"                  # FR
    r"list\s+motywacyjny|"                        # PL
    r"lettera\s+di\s+presentazione|"             # IT
    r"carta\s+de\s+presentaci|"                  # ES
    r"сопровод",                                  # RU
    re.I)

# Поля-загрузки, куда резюме класть НЕЛЬЗЯ, даже если мы не знаем, что там нужно.
# «Additional documents» — не поле резюме: своё резюме уже загружено, и второй
# копией мы вытеснили бы то, чего работодатель там ждал.
_NOT_A_RESUME_UPLOAD_RE = re.compile(
    r"portfolio|photo|picture|certificate|transcript|other|"
    r"additional\s+document|supporting\s+document|документ",
    re.I)

# Что в `accept` означает «PDF сюда можно».
_PDF_ACCEPT = frozenset({".pdf", "application/pdf", "application/*", "*/*", "*"})


def _takes_documents(accept: str) -> bool:
    """Примет ли файловое поле PDF — по его `accept`. Пусто — примет что угодно."""
    tokens = {t.strip().lower() for t in (accept or "").split(",") if t.strip()}
    return not tokens or bool(tokens & _PDF_ACCEPT)

# «Сколько лет опыта»: и общий вопрос, и привязанный к технологии, EN и RU.
# «experience» без слова про годы сюда не входит намеренно — это уже просьба
# рассказать, а не назвать число.
_EXPERIENCE_RE = re.compile(
    # «Годы» и «опыт» рядом, в любом порядке и с названием стека между ними:
    # «Years of Python experience», «Experience with React (years)». Раньше
    # требовалось, чтобы слова стояли вплотную, и вопрос с вписанным стеком
    # проходил мимо — а обязательное поле утаскивало заявку в manual. Ответ от
    # технологии не зависит (просьба владельца профиля 2026-08-22), поэтому
    # промежуток и нужен. Он ограничен 20 символами, а подпись целиком —
    # _MAX_LABEL_CHARS: это по-прежнему короткий вопрос про число.
    r"years?\b[^\n]{0,20}\bexperience|experience\b[^\n]{0,20}\byears?|"
    # «Опыт работы (лет)» — между словами стоит ещё одно, поэтому не \w*, а
    # короткий промежуток: длинную прозу всё равно отсечёт _MAX_LABEL_CHARS.
    r"how\s+many\s+years|опыт[^\n]{0,15}лет|лет\s+опыта|стаж|"
    # Вакансии в Европе спрашивают на своём языке, а ответ от языка не зависит.
    # Живьём 2026-09-16 (лид #1315, Easy Apply, шаг 3): «Depuis combien d’années
    # utilisez-vous Microsoft Azure ?» и тот же вопрос про AWS остались пустыми,
    # и заявка ушла в ручные. Апостроф у французов бывает типографский (’) и
    # обычный ('), поэтому оба.
    r"combien\s+d[’']?\s*ann[ée]es|ann[ée]es?\b[^\n]{0,20}\bexp[ée]rience|"
    r"wie\s+viele\s+jahre|jahre?\b[^\n]{0,20}\berfahrung|"
    # Живьём 2026-09-17 (лид #1421, Mática Partners): «¿Cuántos años de
    # experiencia tienes con LangChain?» — ответ ушёл свободным текстом, и
    # LinkedIn отверг его как «Invalid input». Ударение и «ñ» пишут не всегда,
    # поэтому оба написания.
    r"cu[áa]ntos\s+a[ñn]os|a[ñn]os\b[^\n]{0,20}\bexperiencia",
    re.I)

# Число внутри варианта списка: «3-5 years» -> 3, «5+» -> 5.
_LEADING_NUMBER = re.compile(r"\d+")


# Сколько лет обещает вариант списка. Читается именно ОТРЕЗОК, а не первое
# попавшееся число: «Under 2 years» это 0..1, а не «два», и «2-5 years» это
# 2..5, внутрь которого попадают три года — см. _experience_answer.
_YEARS_RANGE_RE = re.compile(r"(\d+)\s*[-–—]\s*(\d+)")
_YEARS_PLUS_RE = re.compile(
    r"(\d+)\s*(?:\+|or more|and (?:more|above|up)|или больше|или более|и более)", re.I)
_YEARS_UNDER_RE = re.compile(
    r"(?:under|less than|below|fewer than|up to|<|до|менее|меньше)\s*(\d+)", re.I)
_YEARS_NONE_RE = re.compile(r"\bno\b|\bnone\b|без опыта|нет опыта|не работал", re.I)
_ANY_NUMBER_RE = re.compile(r"\d+")
_YEARS_UNBOUNDED = 10 ** 6


def _option_years_span(option) -> tuple[int, int] | None:
    """(нижняя, верхняя) граница варианта в годах, или None если чисел нет."""
    text = str(option)
    m = _YEARS_RANGE_RE.search(text)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = _YEARS_PLUS_RE.search(text)
    if m:
        return int(m.group(1)), _YEARS_UNBOUNDED
    m = _YEARS_UNDER_RE.search(text)
    if m:
        return 0, max(0, int(m.group(1)) - 1)
    m = _ANY_NUMBER_RE.search(text)
    if m:
        return int(m.group(0)), int(m.group(0))
    if _YEARS_NONE_RE.search(text):
        return 0, 0
    return None


def _experience_answer(f: FieldObs, years: int) -> FillAction:
    """Ответ на вопрос о годах опыта: число, а в списке — подходящий диапазон.

    Вариант читается как ОТРЕЗОК лет, который он обещает, и выигрывает тот,
    внутрь которого опыт попадает. Раньше бралcя первый вариант, чья нижняя
    граница уже не меньше нужного, и этого хватало ровно до первого списка с
    внутренними диапазонами: на живой форме BlueThrone 2026-08-24 вопрос «How
    many years of production Go experience do you have?» с вариантами
    ['No production Go experience', 'Under 2 years', '2-5 years', '5+ years']
    при трёх годах в профиле получал ответ «5+ years» — правило проскакивало
    «2-5 years», внутри которого тройка и лежит. Работодателю уходило заявление
    о пяти годах production Go, и это не округление, а неправда в анкете.

    На границе («1-3» и «3-5» при трёх годах оба подходят) берётся СТАРШИЙ: это
    то, что человек про себя говорит, и обе формулировки одинаково правдивы.

    Когда не подходит ни один: сначала ближайший снизу — занизить не страшно;
    если и таких нет (весь список выше правды), берётся самый скромный вариант.
    Занижение стоит шанса, завышение — вранья в анкете, и цена разная.
    """
    if not f.options:
        return FillAction(field=f, value=str(years), source="profile")

    spans = [(i, _option_years_span(o)) for i, o in enumerate(f.options)]
    inside = [i for i, s in spans if s and s[0] <= years <= s[1]]
    if inside:
        best = inside[-1]
    else:
        below = [(s[0], i) for i, s in spans if s and s[0] <= years]
        known = [(s[0], i) for i, s in spans if s]
        if below:
            best = max(below)[1]
        elif known:
            best = min(known)[1]
        else:
            best = len(f.options) - 1
    return FillAction(field=f, choice_index=best, value=f.options[best],
                      source="profile")


_NEEDED_RE = re.compile(
    r"(?:требу\w*|нужн\w*|понадоб\w*|will you (?:require|need)|do you (?:require|need))"
    r"[^?]{0,40}(?:разрешени\w*|виз\w*|спонсор\w*|sponsorship|visa|work permit)", re.I)


def _asks_whether_needed(question: str) -> bool:
    """Спрашивают ли, НУЖНО ли разрешение (а не есть ли оно).

    «Требуется ли вам разрешение на работу в Казахстане?» — ответ «нет», и это
    хорошая новость. «Есть ли у вас разрешение на работу в Казахстане?» — ответ
    «да», и это та же хорошая новость. Слова почти одни, смысл обратный.
    """
    return bool(_NEEDED_RE.search(question or ""))


def _names_no_country(question: str) -> bool:
    """Названа ли в вопросе страна. Без неё правило про спонсорство падает
    обратно на флаг анкеты, а не выдумывает ответ."""
    from app.domain.apply_profile import country_in_question
    return not country_in_question(question)


def _yes_no(f: FieldObs, yes: bool, source: str = "profile") -> FillAction:
    if f.options:
        idx = _match_choice(f.options, "yes" if yes else "no")
        if idx is not None:
            return FillAction(field=f, choice_index=idx, value=f.options[idx], source=source)
    return FillAction(field=f, value="Yes" if yes else "No", source=source)


def _age_answer(f: FieldObs, age: int | None) -> FillAction | None:
    """Ответ на вопрос о возрасте из даты рождения, или None — если ответа нет.

    «Are you at least 18 years of age?» — это «да/нет» по порогу, диапазон
    «18-24» выбирается тот, в который попадает возраст, а голый вопрос получает
    число. Прежде на всё это отвечала строка «22» из custom_answers — в том числе
    в группу из «Yes»/«No».
    """
    if age is None:
        return None
    floor = minimum_age_asked(getattr(f, "question", "") or f.label)
    if floor is not None:
        return _yes_no(f, age >= floor)
    if f.options:
        for i, option in enumerate(f.options):
            span = _option_years_span(option)
            if span and span[0] <= age <= span[1]:
                return FillAction(field=f, choice_index=i, value=f.options[i],
                                  source="profile")
        return None
    return FillAction(field=f, value=str(age), source="profile")


def _custom_choice(f: FieldObs, low: str, ans: str) -> FillAction:
    """Готовый ответ владельца на вопрос-список — вариант списка, а не текст.

    Живьём 2026-09-14 (повтор #1216): «notice period: 1 month» из анкеты уезжал в
    `select` строкой, и заполнение падало на обязательном поле. Вариант ищется
    по тексту, срок выхода — по дням; не нашёлся — обязательный вопрос уходит
    модели, как любой другой список без готового ответа.
    """
    idx = _option_index_for(f.options, ans)
    if idx is None and (_NOTICE_RE.search(low) or _AVAILABILITY_DATE_RE.search(low)):
        idx = notice_option_index(f.options, ans)
    if idx is not None:
        return FillAction(field=f, choice_index=idx, value=f.options[idx], source="custom")
    if field_is_required(f):
        return FillAction(field=f, needs_ai=True, source="ai")
    return FillAction(field=f, source="unmapped")


def map_field(f: FieldObs, profile: ApplyProfile, cv_path: str,
              cover_letter_path: str = "") -> FillAction:
    low = f"{f.label} {f.name}".strip().lower()
    # Length is judged on the LABEL alone, never on label+name. Ashby names every
    # field with a UUID ("8d640ab2-9852-452b-9798-92d28cba…"), which adds ~37
    # characters of noise — enough to push any real question past the caption
    # limit and switch off every keyword rule for it. That is what kept the
    # salary question unanswered on lead 123 after the model was already
    # answering it correctly in isolation (measured 2026-07-29).
    # И на ВОПРОСЕ целиком, а не на подписи: скрапер режет подпись до 80 знаков,
    # и абзац в 250 знаков сходил за короткую подпись. Живьём 2026-09-13 (Workable,
    # лид #1164) правило текущей зарплаты нашло в обрубке «2) Current Location
    # 3) Expected salary» и оставило обязательное поле пустым, не спросив модель.
    caption_len = len((getattr(f, "question", "") or f.label or "").strip() or low)

    if f.type == "file":
        # Поле, которое по своему `accept` документов не берёт (фото, аватар), не
        # получает ни резюме, ни письма: подпись могла соврать, объявление — нет.
        if not _takes_documents(getattr(f, "accept", "")):
            return FillAction(field=f, source="unmapped")
        # Сопроводительное письмо — отдельный документ, и оно у нас есть: письмо
        # под эту вакансию уже написано, PDF собирается из него же. Раньше поле
        # оставалось пустым, и обязательное утаскивало заявку в `manual`.
        if COVER_LETTER_RE.search(low):
            if cover_letter_path:
                return FillAction(field=f, value=cover_letter_path, is_file=True,
                                  source="cover_letter")
            return FillAction(field=f, source="unmapped")
        # Attach the CV only to a resume/CV upload — never to a portfolio, photo,
        # or other document field we don't have a file for. Класть сюда резюме
        # нельзя ни при каких условиях: работодатель получит не тот документ, и
        # заметить это будет некому.
        if _NOT_A_RESUME_UPLOAD_RE.search(low):
            return FillAction(field=f, source="unmapped")
        return FillAction(field=f, value=cv_path, is_file=True, source="cv")

    # Personal-status questions belong here too: "Marital Status" is the same kind
    # of question as gender, and "I prefer not to say" is on the form for exactly
    # this reason. Better that than a model guessing at someone's private life.
    if re.search(r"gender|race|ethnic|veteran|disabilit|sexual orientation|pronoun|"
                 r"marital|family status|семейное положение|пол\b", low):
        if f.options:
            idx = _match_choice(f.options, "prefer not", "decline", "not to say")
            if idx is None:
                idx = len(f.options) - 1
            return FillAction(field=f, choice_index=idx, value=f.options[idx], source="eeo")
        return FillAction(field=f, value=EEO_ANSWER, source="eeo")

    # Обе половины одного факта, и обе теперь читают СТРАНУ из вопроса, а не
    # один глобальный флаг: право работать в Швеции и потребность в спонсорстве
    # для Швеции — это про Швецию, а не про Казахстан. Чем это обернулось до
    # починки, см. `work_authorized_in`.
    # Триггеры двуязычные: без русских форма на hh.kz или в русскоязычном ATS
    # до этого правила просто не доходила и уезжала к модели, которая про
    # правовой статус ничего не знает.
    #
    # «ТРЕБУЕТСЯ ли вам разрешение на работу» и «ЕСТЬ ли у вас разрешение на
    # работу» — противоположные вопросы из одних слов, и разводит их только
    # глагол. Вопрос о НУЖДЕ уходит в правило про спонсорство ниже: там ответ
    # «да» означает «нужна виза», а здесь «да» означало бы «право есть».
    if _asks_whether_needed(low):
        pass
    elif re.search(r"authori[sz]ed to work|work authori|eligible to work|right to work"
                   r"|право работать|правом работать|разрешение на работу", low):
        return _yes_no(f, work_authorized_in(f.label or low, profile.country))
    if re.search(r"sponsor|visa|work permit|спонсор|виз[ауы]\b|разрешени\w*\s+на\s+работу",
                 low):
        authorized = work_authorized_in(f.label or low, profile.country)
        # Спонсорство нужно там, где права работать нет. Когда страна в вопросе
        # не названа, остаётся прежний флаг из анкеты — трактовать «нужна ли вам
        # виза?» как «да» для домашней страны было бы такой же неправдой,
        # только в другую сторону.
        needs = profile.needs_visa_sponsorship if _names_no_country(f.label or low) \
            else not authorized
        return _yes_no(f, needs)
    if re.search(r"relocat", low):
        return _yes_no(f, profile.open_to_relocation)

    # ОДИНОЧНАЯ галочка — утверждение («I agree to the privacy policy»), и здесь
    # решается только, соглашаться ли. Группа чекбоксов под одним `name` — это
    # ВОПРОС с вариантами, её разбирает правило ниже вместе с радиокнопками:
    # замер 2026-08-24 на CoinsPaid показал, что без этого «Which versions of
    # React have you worked with?» уходил в `unmapped` и держал отправку уже
    # заполненной формы. Отличает их наличие вариантов: скрапер собирает группу
    # только начиная с двух элементов.
    if f.type == "checkbox" and not f.options:
        # Вопрос целиком, а не подпись: скрапер режет её до 80 знаков. Живьём
        # 2026-09-14 (лид #1218, Action1) «Privacy Notice» и «consent» стояли за
        # обрезом — галочка согласия оставалась пустой, форма не пускала дальше.
        whole = f"{getattr(f, 'question', '') or ''} {low}".lower()
        if re.search(r"agree|consent|privacy|terms|policy|gdpr|authori", whole):
            return FillAction(field=f, value="true", source="profile")
        return FillAction(field=f, value="", source="unmapped")

    # Whole-word match, not substring: the label comes from a third-party page, so
    # a key like "salary" used as a substring would also fire on "your friend's
    # salary" or "salary of your last manager" and hand over a prepared answer.
    label_words = set(re.findall(r"[a-zа-яё0-9]+", low))
    for key, ans in profile.custom_answers.items():
        key = (key or "").strip().lower()
        if not key:
            continue
        key_words = re.findall(r"[a-zа-яё0-9]+", key)
        if not key_words:
            continue
        if len(key_words) == 1:
            matched = key_words[0] in label_words
        else:                       # multi-word key: match the phrase in order
            matched = re.search(r"\b" + r"\W+".join(map(re.escape, key_words)) + r"\b", low)
        if matched:
            if ans and f.options:
                return _custom_choice(f, low, ans)
            if ans:
                # Перевод в единицы вопроса — НЕ отмена ответа владельца, а его
                # выражение. `custom_answers` содержит «notice period: 1 month»,
                # и эта ветка стоит раньше перевода: живьём 2026-09-05 (лид
                # #877, повтор уже с правкой) в поле «notice period in days»
                # снова уехало «1 month» — семь знаков, «Недопустимое значение».
                return FillAction(field=f, value=_in_asked_units(low, ans),
                                  source="custom")
            return FillAction(field=f, needs_ai=True, source="ai")

    # Дата рождения и возраст — факты анкеты, а не вопросы к модели: даты она не
    # знает, а угаданная ушла бы работодателю как факт. Живьём 2026-09-14 (лид
    # #1216, LinkedIn Easy Apply) обязательное «Date Of Birth *» стояло пустым и
    # держало весь отклик. Формат — тот, что ждёт поле (`birth_date_text`); без
    # даты в анкете поле честно остаётся пустым.
    #
    # Только короткая подпись: абзац «full name, date of birth and why…» — вопрос
    # для модели, одной датой он не отвечается.
    if caption_len <= _MAX_LABEL_CHARS and asks_date_of_birth(low):
        text = "" if f.options else birth_date_text(
            profile.date_of_birth, field_type=f.type, placeholder=f.placeholder,
            lang=f.lang, picker=f.date_picker)
        if text:
            return FillAction(field=f, value=text, source="profile")
        return FillAction(field=f, source="unmapped")
    if caption_len <= _MAX_LABEL_CHARS and asks_age(low):
        answer = _age_answer(f, age_on(profile.date_of_birth, date.today()))
        if answer is not None:
            return answer

    # «Сколько лет опыта» — вопрос с готовым ответом, а не повод звать модель.
    # Замер 2026-08-03: до этого правила он возвращал `unmapped` во всех
    # формулировках, и обязательное поле утаскивало всю заявку в `manual`, уже
    # потратив генерацию письма и поднятый браузер. Встречается и в формах ATS,
    # и в LinkedIn Easy Apply.
    #
    # Ограничение по длине подписи — как у зарплаты: «Расскажите об опыте работы
    # в распределённых командах» это проза, и подставлять туда число бессмысленно.
    if (caption_len <= _MAX_LABEL_CHARS and profile.min_experience_years > 0
            and _EXPERIENCE_RE.search(low)):
        return _experience_answer(f, profile.min_experience_years)

    # Salary is the one recognised field whose right answer depends on the JOB, not
    # on a number we carry around: "minimum you would accept, in £ per month" has a
    # different answer for a London fintech and a remote contract. A fixed
    # `desired_salary` still wins when it is set; otherwise the model answers it
    # with the vacancy in front of it. Handled before the caption rules because
    # those would return "recognised but empty" and leave a REQUIRED salary box
    # blank, which parks the whole application.
    # Caption-length only, like every other keyword rule: "Describe a project where
    # you justified the salary budget of your team" is prose, and handing it a
    # stored figure instead of an answer is exactly what _MAX_LABEL_CHARS exists
    # to prevent. Longer labels fall through to the free-text branch below, which
    # sends them to the model anyway.
    # ТЕКУЩАЯ зарплата — раньше общей ветки и отдельно от неё. Общая отдаёт
    # ОЖИДАЕМУЮ всему, где есть слово «salary», и на вопросе «What is your
    # current salary ?» это уверенно сообщало работодателю неверный факт о
    # человеке (поймано тестом 2026-09-05; ветка существовала задолго до него).
    #
    # Цифры владельца нет — спрашиваем модель. Решение владельца 2026-09-13:
    # средняя Strong Middle по рынку страны вакансии, без страны — по Казахстану
    # (правило в `_QUESTIONS_SYSTEM`). Прежде поле оставалось пустым, и «Current
    # CTC» уводил отклик в ручной (лиды #339, #864–#866, #881, #961, #997).
    if (caption_len <= _MAX_LABEL_CHARS
            and _CURRENT_SALARY_RE.search(low)
            and re.search(r"salary|compensation|ctc\b|зарплат|оклад", low)):
        if profile.current_salary:
            return FillAction(field=f, value=profile.current_salary, source="profile")
        return FillAction(field=f, needs_ai=True, source="ai")

    if (caption_len <= _MAX_LABEL_CHARS
            and re.search(r"salary|compensation|expected pay|\brate\b|зарплат|оклад", low)):
        if profile.desired_salary:
            return FillAction(field=f, value=profile.desired_salary, source="profile")
        return FillAction(field=f, needs_ai=True, source="ai")

    # Контрол `input[type=date]` принимает только YYYY-MM-DD. Строка из профиля
    # («1 month») в него не встаёт вовсе — замер 2026-08-26 на BlueThrone, где
    # обязательное «Please enter your available start date» останавливало заявку.
    # Поэтому дата считается, а не пересказывается.
    #
    # И только про НАШУ доступность. Дату выпуска или даты прошлой работы мы не
    # знаем, и подставлять туда день выхода нельзя: это уйдёт работодателю как
    # факт биографии, которого не было. Такое поле остаётся пустым и честно
    # удерживает отправку.
    if f.type == "date":
        if _AVAILABILITY_DATE_RE.search(low):
            iso = availability_iso(profile.notice_period)
            if iso:
                return FillAction(field=f, value=iso, source="profile")
        return FillAction(field=f, source="unmapped")
    # Та же дата, но текстовым полем с форматом: Indeed Apply держит «What is your
    # last working date?» как `input type=text`, а `MM/dd/yyyy` лежит в данных
    # страницы (#1228, 2026-09-14); календарь LinkedIn — вход с lang. Модель такую
    # дату не знает и честно оставляла поле пустым.
    if (caption_len <= _MAX_LABEL_CHARS and not f.options
            and (looks_like_date_pattern(f.placeholder) or f.date_picker)
            and _AVAILABILITY_DATE_RE.search(low)):
        iso = availability_iso(profile.notice_period)
        if iso:
            return FillAction(field=f, value=date_for_field(
                iso, placeholder=f.placeholder, lang=f.lang, picker=f.date_picker),
                source="profile")

    # _LABEL_RULES match anywhere in the label, which is right for a real caption
    # ("Email", "Your phone number") but wrong for prose: a question ending in
    # "…и укажи email кандидата" would otherwise hand over the address without the
    # model ever being asked. Real captions are short, so prose skips these rules
    # and falls through to the free-text branch below.
    # Срок выхода СПИСКОМ — вариант выбирается по дням, а не по буквам. Живьём
    # 2026-09-14 (лид #1216, LinkedIn Easy Apply): «What is your current notice
    # period?*» c «Immediate Joiner / Less than 30 Days / 30 Days / …»; строка
    # «1 month» буквально ни с чем не совпала, ответ модели в список не встал, и
    # отклик остановился на обязательном поле. Раньше правил про единицы ниже:
    # число «30» в выпадающий список не вписать.
    if (caption_len <= _MAX_LABEL_CHARS and f.options
            and (_NOTICE_RE.search(low) or _AVAILABILITY_DATE_RE.search(low))):
        idx = notice_option_index(f.options, profile.notice_period)
        if idx is not None:
            return FillAction(field=f, choice_index=idx, value=f.options[idx],
                              source="profile")

    # Срок отработки, спрошенный В ЕДИНИЦАХ. Профиль хранит одну строку («1
    # month»), а вопрос приходит в трёх видах — «(in weeks)», «in days», просто
    # «notice period?» — и первые два поля числовые. Строка уезжала во все три
    # как есть, LinkedIn отвечал «Недопустимое значение», экран не менялся
    # (живьём 2026-09-05, вакансии 4461771754 и 4461119453).
    #
    # Перевод, а не догадка: единицу называет сам вопрос, число берётся из
    # профиля. Не перевелось — правило молчит, и вопрос достаётся общему пути.
    if caption_len <= _MAX_LABEL_CHARS and _NOTICE_RE.search(low):
        converted = _in_asked_units(low, profile.notice_period)
        if converted != profile.notice_period:
            return FillAction(field=f, value=converted, source="profile")

    # Код страны телефона — вариант из списка, а не номер целиком: правило
    # телефона ниже искало бы среди «Spain (+34)» весь «+7 775 720 0604» и не
    # нашло бы ничего. Сам номер потом теряет код в `_drop_duplicated_country_code`.
    if f.options and _COUNTRY_CODE_LABEL_RE.search(low):
        idx = _country_code_option(f.options, profile)
        if idx is not None:
            return FillAction(field=f, choice_index=idx, value=f.options[idx],
                              source="profile")

    # Почтовый индекс — не «город, страна», даже когда имя поля «location-postal-
    # code»: правило места читает подпись вместе с именем и вписало «Astana,
    # Kazakhstan» в «Zip code» (Indeed Apply, #1236, 2026-09-14). Индекса в анкете
    # нет, а выдуманный уйдёт работодателю как адрес.
    # И не улица: «Street address» с name="location-address" получил «Astana,
    # Kazakhstan» тем же путём (#1236, прогон 10). Улицы в анкете тоже нет.
    if _POSTAL_RE.search(low) or _STREET_RE.search(low):
        return FillAction(field=f, source="unmapped")

    if caption_len <= _MAX_LABEL_CHARS:
        for rx, resolver in _LABEL_RULES:
            if rx.search(low):
                val = resolver(profile)
                if not val:
                    # Recognised field (linkedin/website/salary/…) but no profile
                    # value: leave it empty rather than dumping AI prose into it.
                    # Пока оно необязательное. Обязательное отдаём модели: у неё
                    # в руках резюме и профиль, так что ответ берётся из них, а
                    # не выдумывается, — и это лучше, чем потерять всю заявку
                    # из-за одной строки, которой не оказалось в apply_profile.
                    if field_is_required(f):
                        return FillAction(field=f, needs_ai=True, source="ai")
                    return FillAction(field=f, source="unmapped")
                if f.options:
                    # A dropdown takes an option, not typed text — .fill() on a
                    # <select> raises, and that raise on a REQUIRED field is a
                    # manual apply. LinkedIn serves email as a select of the
                    # account's verified addresses.
                    idx = _option_index_for(f.options, val)
                    if idx is None:
                        # Ответ у нас есть, но в ЭТОМ списке его нет. Обязательное
                        # поле-ВЫБОР отдаём модели — тем же доводом, что строкой
                        # выше, где факта в профиле нет вовсе, и что в
                        # `_load_combobox_options`, где готовый ответ мимо словаря
                        # виджета тоже становится вопросом к модели.
                        #
                        # Замер живьём 2026-08-27, TradingView на Teamtailor
                        # (лента remocate): «Locations*Required» — не согласие и
                        # не одиночная галочка, а ТРИ чекбокса под одним `name`,
                        # то есть вопрос с вариантами Tbilisi / Limassol / Paphos.
                        # Подпись ловило правило `location`, профиль отвечал
                        # «Astana, Kazakhstan», и одиннадцать заполненных полей
                        # из двенадцати держало это одно. Знать БОЛЬШЕ и делать
                        # МЕНЬШЕ — расхождение, а не осторожность: то же поле без
                        # слова «location» в подписи модель отвечает уже сейчас,
                        # веткой «f.options и обязательное» ниже.
                        #
                        # Контакты сюда не попадают, см. `_ONE_TRUE_VALUE_RE`.
                        # Необязательное не трогаем и здесь: отправку оно не
                        # держит, а цена ответа на чужой необязательный виджет
                        # измерена 2026-07-29 (переключатель языка LinkedIn).
                        if field_is_required(f) and not _ONE_TRUE_VALUE_RE.search(low):
                            return FillAction(field=f, needs_ai=True, source="ai")
                        return FillAction(field=f, source="unmapped")
                    return FillAction(field=f, choice_index=idx,
                                      value=f.options[idx], source="profile")
                return FillAction(field=f, value=val, source="profile")

    # Free text only: a textarea, or an input whose label reads like an open question.
    if f.tag == "textarea" or re.search(
            r"why|cover letter|message|motivat|tell us|describe|\bnote\b|question|"
            r"about you|about yourself|yourself", low):
        return FillAction(field=f, needs_ai=True, source="ai")
    # An unrecognised dropdown gets an AI answer ONLY when the form requires one.
    # Optional ones are left strictly alone: not every <select> on a page belongs
    # to the application. LinkedIn's Easy Apply renders its interface-language
    # picker inside the contact step, and this rule answered it — the model took
    # the first option and switched the whole account to Arabic (observed
    # 2026-07-29, ar_AE, restored by hand). Every text-based selector then stopped
    # matching, so the flow could not be driven either. A required dropdown we
    # must answer is a fair thing to guess at; an optional one is somebody else's
    # setting, and the cost of touching it is unbounded.
    # A RADIO group is a question by construction — several labelled answers to
    # one prompt, inside an application form — so it gets answered whether or not
    # the DOM bothered to mark it required. Ashby marks none of them, and the form
    # then refuses the submit for a field nothing had flagged.
    #
    # A `select` still needs the required flag. That is the control the language
    # picker turned out to be, and answering optional ones cost the account its
    # interface language; the distinction is what keeps both lessons.
    # Группа чекбоксов приравнена к радиогруппе по тому же основанию: несколько
    # подписанных ответов на один вопрос внутри формы отклика — это вопрос, кто
    # бы там ни забыл проставить `required`.
    #
    # «Форма требует» читается и по подписи: Personio рисует «Wie stufst du dein
    # deutsches Sprachniveau ein?* (erforderlich)» вообще без `required` в DOM, и
    # молчать в ответ значит держать отправку из-за поля, которое мы сами и
    # отказались заполнить. Переключателя языка это не касается — на нём пометки
    # нет, и он по-прежнему остаётся чужой настройкой.
    if f.options and (field_is_required(f) or f.type in ("radio", "checkbox")):
        return FillAction(field=f, needs_ai=True, source="ai")

    # Незнакомое короткое поле. ОБЯЗАТЕЛЬНОЕ отдаём модели: прогон по Remocate
    # 2026-08-24 показал цену прежнего решения — три формы (Datadog, N26,
    # CoinsPaid) открылись, письмо было написано, браузер поднят, а отправку
    # сорвало одно поле вроде «Please indicate your notice period in months» или
    # «Which is your preferred working location?», под которое в профиле просто
    # нет строки. Спросить модель дешевле, чем потерять заявку, и безопаснее, чем
    # кажется: у неё в руках резюме, профиль и текст вакансии.
    #
    # НЕОБЯЗАТЕЛЬНОЕ по-прежнему не трогаем, и это не осторожность ради
    # осторожности: отправку оно не блокирует, то есть заполнять его нечего ради,
    # а цена ошибки измерена — ответ на чужой необязательный виджет (переключатель
    # языка интерфейса в LinkedIn) увёз весь аккаунт на арабский 2026-07-29.
    #
    # «Спросили модель» не равно «заполнили»: если ответа не будет,
    # `unmapped_required` так же удержит отправку, и полупустая анкета
    # работодателю не уйдёт.
    if field_is_required(f):
        return FillAction(field=f, needs_ai=True, source="ai")
    return FillAction(field=f, source="unmapped")


def _option_index_for(options: list[str], value: str) -> int | None:
    """Index of the option carrying `value`, or None when none does.

    Exact match first, then containment either way — an option may read
    "Kazakhstan (+7)" for a value of "+7", or "ivan@x.com" for "Ivan@X.com".
    """
    v = (value or "").strip().lower()
    if not v:
        return None
    opts = [(o or "").strip().lower() for o in options]
    for i, o in enumerate(opts):
        if o == v:
            return i
    for i, o in enumerate(opts):
        if o and (v in o or o in v) and not _PLACEHOLDER_OPTION_RE.match(o):
            return i
    return None


# «Phone prefix» у Factorial и «Dial code» — тот же вопрос, что «country code» у
# LinkedIn Easy Apply (живьём 2026-09-13, лид #1044: список остался на «Spain
# (+34)», в «Phone» ушёл номер с +7, сервер ответил «Something went wrong»).
_COUNTRY_CODE_LABEL_RE = re.compile(
    r"country[\s_-]*code|код страны|phone[\s_-]*prefix|dial(?:ing)?[\s_-]*code|"
    r"calling[\s_-]*code", re.IGNORECASE)
_PHONE_CODE_RE = re.compile(r"^\s*\+(\d{1,3})")


def _country_code_option(options: list[str], profile: ApplyProfile) -> int | None:
    """Вариант списка кодов страны для телефона из профиля, или None.

    Код бывает общим у нескольких стран (+7 — Россия и Казахстан), поэтому сначала
    вариант, где есть и код, и страна профиля, и только потом первый с тем же кодом.
    """
    m = _PHONE_CODE_RE.match(profile.phone or "")
    if not m:
        return None
    code = re.compile(rf"\+{m.group(1)}(?!\d)")
    country = (profile.country or "").strip().lower()
    with_code = [i for i, o in enumerate(options) if code.search(o or "")]
    for i in with_code:
        if country and country in (options[i] or "").lower():
            return i
    return with_code[0] if with_code else None
_PHONE_LABEL_RE = re.compile(r"phone|mobile|телефон|whats\s?app|contact\s*(?:number|no\b)",
                             re.IGNORECASE)
_LEADING_COUNTRY_CODE_RE = re.compile(r"^\+\d{1,3}[\s\-()]*")


def _drop_duplicated_country_code(actions: list[FillAction]) -> None:
    """Strip the country code from a phone value when the form asks for it apart.

    LinkedIn's Easy Apply carries a «Phone country code» select (already set to
    "Kazakhstan (+7)") beside an empty «Mobile phone number». The profile holds
    one full number, "+7 775 720 0604", so typing it into the second control
    submits the code twice. Workday and Greenhouse split the same way.
    """
    if not any(_COUNTRY_CODE_LABEL_RE.search(f"{a.field.label} {a.field.name}")
               for a in actions):
        return
    for a in actions:
        if a.choice_index is not None or not a.value:
            continue
        low = f"{a.field.label} {a.field.name}"
        if _PHONE_LABEL_RE.search(low) and not _COUNTRY_CODE_LABEL_RE.search(low):
            a.value = _LEADING_COUNTRY_CODE_RE.sub("", a.value).strip()


_RESUME_LABEL_RE = re.compile(r"resume|\bcv\b|резюме", re.IGNORECASE)


def _only_the_real_resume_field(actions: list[FillAction]) -> None:
    """When a form has several file inputs, upload only to the one asking for a CV.

    Ashby puts an unlabelled "Autofill from resume" dropzone above its actual
    application form. Uploading there is not part of applying — it makes the
    server REBUILD the form (`ApiAutofillApplicationFormWithUploadedResume`
    returns a new render id), so every value set around it belongs to a form that
    no longer exists, and the Submit that follows fires no request at all
    (measured on lead 123, 2026-07-29: 22 setFormValue calls, zero submits).

    An unlabelled file input is only used when nothing on the form names a resume.
    """
    # Сопроводительное письмо сюда не попадает: оно нацелено осознанно, по
    # подписи поля, а правило написано против БЕЗЫМЯННОГО дропзона Ashby.
    files = [a for a in actions if a.is_file and a.source != "cover_letter"]
    if len(files) < 2:
        return
    named = [a for a in files
             if _RESUME_LABEL_RE.search(f"{a.field.label} {a.field.name}")]
    if not named:
        return
    for a in files:
        if a not in named:
            a.is_file, a.value, a.source = False, "", "unmapped"


def build_plan(obs: PageObservation, profile: ApplyProfile, cv_path: str,
               cover_letter_path: str = "") -> ApplyPlan:
    actions = [map_field(f, profile, cv_path, cover_letter_path)
               for f in obs.fields if is_fillable_field(f)]
    _drop_duplicated_country_code(actions)
    _only_the_real_resume_field(actions)
    return ApplyPlan(actions=actions)


# Вопрос, ответом на который может быть только число. Раньше об этом судили по
# `type == "number"`, и у LinkedIn это не срабатывало никогда: там ВСЕ поля
# `type="text"`, включая «How many years…» и «notice period (in weeks)». Живьём
# 2026-09-05 (вакансия 4461771754) в поле «notice period (in weeks)» уехало
# «1 month», страница ответила «Недопустимое значение», и экран не сменился
# шесть раз подряд.
#
# Зарплаты здесь НАМЕРЕННО нет, хотя она тоже про число: у владельца может быть
# решение её не раскрывать, и «ответь только числом» это решение отменило бы.
# Ей хватает предела длины — короткий отказ в двадцать знаков помещается.
_NUMERIC_Q_RE = re.compile(
    r"how many|years of (work )?experience|\(in weeks\)|\(in months\)|"
    r"\(in years\)|notice period|сколько лет|сколько месяцев|сколько недель",
    re.I)


# Зарплата — тоже число, и поле под неё у LinkedIn числовое: ответ «не указываю»
# оно отвергает «Недопустимым значением» так же, как фразу (живьём 2026-09-05,
# вакансии 4461771754 и 4463333146 — «Current CTC», «ECTC in lakhs per annum»).
#
# ТЕКУЩАЯ зарплата до 2026-09-13 была исключена как факт о владельце. С
# 2026-09-13 владелец решил иначе: без цифры в `current_salary` модель оценивает
# её по рынку страны вакансии (Strong Middle, без страны — Казахстан), так что
# это тоже число.
def _in_asked_units(question: str, value: str) -> str:
    """Значение в единицах, которые называет вопрос, — или как было.

    Одно место на оба пути: и на `custom_answers`, и на строку профиля. Разными
    их делать нельзя — вопрос «notice period in days» приходит один и тот же, а
    ответ на него брался бы то переведённым, то нет.
    """
    if not _NOTICE_RE.search(question or ""):
        return value
    return notice_period_in(question, value) or value


def renumber_notice_answers(plan) -> list:
    """Срок отработки числом ДНЕЙ — для полей, где форма отвергла строку.

    Живьём 2026-09-13 (лиды #339, #866, #997, LinkedIn Easy Apply): «Notice
    Period?» без единицы получил строку профиля «1 month», и LinkedIn ответил
    «Invalid input» — поле числовое. Вопрос без единицы правило перевода не трогает
    (`notice_period_in` отдаёт пусто), и это верно, пока форма строку принимает; а
    после отказа нужно число. Дни — так срок считают формы индийского рынка, откуда
    эти вакансии (рядом у них «Current CTC»).

    Возвращает изменённые действия: их и надо заполнить заново.
    """
    changed = []
    for a in plan.actions:
        question = getattr(a.field, "question", "") or a.field.label or a.field.name or ""
        value = (a.value or "").strip()
        if not value or value.isdigit() or not _NOTICE_RE.search(question):
            continue
        days = notice_period_in("notice period in days", value)
        if days:
            a.value = days
            changed.append(a)
    return changed


def _asks_for_a_number(field) -> bool:
    if (field.type or "").lower() == "number":
        return True
    label = field.label or field.name or ""
    if _NUMERIC_Q_RE.search(label):
        return True
    # Текущая зарплата — тоже число: с 2026-09-13 модель её оценивает (решение
    # владельца), а поле под неё у LinkedIn числовое и фразу отвергает.
    return bool(_SALARY_Q_RE.search(label))


def _ai_prompt(field) -> str:
    """Вопрос модели вместе с тем, что поле готово принять.

    Ограничения приходят от самой страницы и стоят одной строки в промпте, а их
    отсутствие стоит отклика: ответ, который в поле не влезает, LinkedIn не
    отвергает вслух — он молча не даёт экрану смениться.
    """
    # Вопрос целиком, а не обрезанная подпись: см. FieldObs.question.
    prompt = getattr(field, "question", "") or field.label or field.name or ""
    lo, hi = getattr(field, "range_min", ""), getattr(field, "range_max", "")
    if getattr(field, "type", "") == "range" and lo and hi:
        # Шкала: без границ модель отвечала по своей мерке (лид #1237, шкала 1–5).
        prompt += f" (ответ: ТОЛЬКО число от {lo} до {hi})"
    elif _asks_for_a_number(field):
        prompt += " (ответ: ТОЛЬКО число, без валюты, символов и слов)"
    limit = getattr(field, "max_len", 0) or 0
    if limit:
        prompt += f" (не длиннее {limit} знаков)"
    return prompt


def _fit_answer(value: str, field) -> str | None:
    """Ответ, укладывающийся в поле, — или None, если уложить нечем.

    None, а не обрезка. Обрезанная фраза уезжает работодателю целым
    предложением без конца, и читает её человек; лучше честно оставить поле
    незаполненным, и пусть про него скажут по имени. Исключение — числовой
    вопрос: там из ответа достаётся само число, и это не догадка, а ровно то,
    что спрашивали.
    """
    limit = getattr(field, "max_len", 0) or 0
    if not limit or len(value) <= limit:
        return value
    if _asks_for_a_number(field):
        m = re.search(r"\d[\d\s.,]*", value)
        if m:
            digits = re.sub(r"[^\d]", "", m.group(0))[:limit]
            if digits:
                return digits
    return None


def answer_ai_fields(plan: ApplyPlan, answerer, vacancy_context: str) -> None:
    """Fill needs_ai actions using the injected answerer. Reuses hh_questions.fill_plan
    to clamp choices and normalise text, keeping one answer format across channels.

    Контакты в ответах модели приводятся к каноническим раньше, на самом
    answerer-е (см. registry._hh_answerer): так один и тот же ник уходит и в
    форму отклика, и в опросник hh, который сюда не заходит вовсе."""
    from app.application.hh_questions import fill_plan

    ai_actions = plan.ai_fields
    if not ai_actions or answerer is None:
        return
    questions = [{
        "id": str(i),
        "type": "choice" if a.field.options else "text",
        "prompt": _ai_prompt(a.field),
        "options": a.field.options,
    } for i, a in enumerate(ai_actions)]

    answers = answerer(questions, vacancy_context) or {}
    tuples = fill_plan(questions, answers)          # [(kind, id, value_or_index), ...]
    by_id = {t[1]: t for t in tuples}
    for i, a in enumerate(ai_actions):
        t = by_id.get(str(i))
        if not t:
            continue
        kind, _, val = t
        if kind == "text":
            fitted = _fit_answer(str(val), a.field)
            if fitted is None:
                continue        # в поле не влезает — пусть его назовёт человек
            a.value = fitted
        else:
            idx, options = int(val), a.field.options
            # Модель без ответа получает первый вариант (`fill_plan` зажимает
            # индекс), а первым часто стоит «Select an option». Выбрать эту
            # заглушку нельзя, и заполнение падало с «не смог заполнить» (лид
            # #1216, 2026-09-14). Пусть поле назовут по имени.
            if options and 0 <= idx < len(options) \
                    and _PLACEHOLDER_OPTION_RE.match(options[idx].strip()):
                continue
            a.choice_index = idx
            if options and 0 <= idx < len(options):
                a.value = options[idx]
