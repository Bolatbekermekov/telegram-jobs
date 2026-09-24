"""Жёсткие требования вакансии, которые кандидат не может выполнить. Чистая логика.

Право работать без спонсорства визы у кандидата есть только в домашней стране.
На вопрос формы «Are you legally authorized to work in X?» бот честно отвечает
«No» (`apply_profile.work_authorized_in`), а Greenhouse, Ashby и Lever держат
такие вопросы как knockout: заявку отклоняет сам ATS, человек её не видит. Без
этой проверки прогон платил описанием, оценкой, письмом и браузером за отклик,
который отсеется автоматически.

Правило намеренно узкое и блокирует только ЯВНО написанное требование:

* гражданство / допуск / «открыто только для <национальность>» — всегда;
* «нужно находиться в X» и «нужно право работать в X» — если работодатель
  при этом не предлагает визу;
* «визу не спонсируем» + локация в чужой стране — если это не удалёнка
  откуда угодно.

Страна в локации сама по себе НЕ блокирует: релокация со спонсорством возможна
(кандидат к ней готов), а удалёнку могут оформить контрактом. Незнакомое слово
после «based in» (город, «the office») тоже не блокирует — ошибиться в сторону
лишнего отклика дешевле, чем выбросить подходящую вакансию.
"""
import re
from dataclasses import dataclass, field


@dataclass
class Eligibility:
    eligible: bool = True
    blocking_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# --- места -------------------------------------------------------------------
#
# Каноническое имя -> варианты написания. Регионы, в которые входит сам
# кандидат («worldwide», «CIS», «Central Asia»), живут в `_NEUTRAL`: встретив их
# в списке («Europe or Central Asia»), требование считаем выполнимым.
_PLACES = {
    "United States": (r"united\s+states(?:\s+of\s+america)?", r"(?<!latin\s)america[n]?",
                      r"сша"),
    "United Kingdom": (r"united\s+kingdom", r"great\s+britain", r"britain", r"british",
                       r"england"),
    "European Union": (r"european\s+union", r"europe(?:an)?", r"eea", r"европ\w*"),
    "Canada": (r"canad(?:a|ian)",),
    "Germany": (r"german(?:y)?", r"германи\w*"),
    "Netherlands": (r"(?:the\s+)?netherlands", r"dutch", r"holland"),
    "Poland": (r"poland", r"polish", r"польш\w*"),
    "France": (r"france", r"french"),
    "Italy": (r"ital(?:y|ian)",),
    "Spain": (r"spain", r"spanish"),
    "Portugal": (r"portugal", r"portuguese"),
    "Switzerland": (r"switzerland", r"swiss"),
    "Sweden": (r"swed(?:en|ish)",),
    "Norway": (r"norw(?:ay|egian)",),
    "Denmark": (r"denmark", r"danish"),
    "Finland": (r"finland", r"finnish"),
    "Ireland": (r"ireland", r"irish"),
    "Austria": (r"austria[n]?",),
    "Belgium": (r"belgi(?:um|an)",),
    "Czechia": (r"czech(?:ia|\s+republic)?",),
    "Romania": (r"romania[n]?",),
    "Cyprus": (r"cyprus", r"кипр\w*"),
    "Israel": (r"israel(?:i)?",),
    "India": (r"india[n]?",),
    "Pakistan": (r"pakistan(?:i)?",),
    "Singapore": (r"singapore(?:an)?",),
    "Australia": (r"australia[n]?",),
    "New Zealand": (r"new\s+zealand",),
    "UAE": (r"united\s+arab\s+emirates", r"dubai", r"оаэ"),
    "Saudi Arabia": (r"saudi(?:\s+arabia)?",),
    "Qatar": (r"qatar",),
    "Japan": (r"japan(?:ese)?",),
    "China": (r"china", r"chinese"),
    "Brazil": (r"brazil(?:ian)?",),
    "Mexico": (r"mexic(?:o|an)",),
    "Latin America": (r"latin\s+america", r"latam"),
    "Philippines": (r"philippines", r"filipino"),
    "Vietnam": (r"vietnam(?:ese)?",),
    "Nigeria": (r"nigeria[n]?",),
    "Egypt": (r"egypt(?:ian)?",),
    "South Africa": (r"south\s+africa[n]?",),
    "Turkey": (r"turkey", r"t[üu]rkiye", r"turkish"),
    "Ukraine": (r"ukrain(?:e|ian)",),
    "Russia": (r"russia[n]?", r"росси\w*", r"рф", r"российск\w*"),
    "Belarus": (r"belarus", r"беларус\w*", r"белорусс\w*"),
    "Kazakhstan": (r"kazakh(?:stan|stani)?", r"казахстан\w*", r"рк"),
}
# Короткие аббревиатуры ловятся ТОЛЬКО заглавными: «us» в «join us» или «uk» в
# чужом слове — не страна.
_UPPER_PLACES = {
    "United States": r"U\.?S\.?A?\.?",
    "United Kingdom": r"U\.?K\.?",
    "European Union": r"E\.?U\.?",
    "UAE": r"UAE",
}
_NEUTRAL = re.compile(
    r"\b(?:worldwide|anywhere|globally|global|any\s+country|any\s+location|"
    r"central\s+asia|cis|emea|asia|eurasia|снг|любой\s+(?:точки|страны))\b", re.I)

_PLACE_RES = [(name, re.compile(r"(?<![\w-])(?:" + "|".join(v) + r")(?![\w-])", re.I))
              for name, v in _PLACES.items()]
_PLACE_RES += [(name, re.compile(r"(?<![\w.])" + rx + r"(?![\w])"))
               for name, rx in _UPPER_PLACES.items()]


def _canon(country: str) -> str:
    for name, rx in _PLACE_RES:
        if rx.fullmatch((country or "").strip()):
            return name
    return (country or "").strip()


def _places_in(window: str) -> tuple[list[str], bool]:
    """Страны в куске текста, в порядке появления, и есть ли там нейтральный регион."""
    hits = sorted((m.start(), name) for name, rx in _PLACE_RES
                  if (m := rx.search(window)))
    return list(dict.fromkeys(n for _, n in hits)), bool(_NEUTRAL.search(window))


# --- требования ----------------------------------------------------------------

# Конец предложения. Точка внутри «U.S.» концом не считается: после неё идёт
# буква или пробел со строчной, а не пробел с заглавной.
_SENTENCE_END = re.compile(r"[;!?\n]|\.(?=\s+[A-ZА-ЯЁ]|\s*$)")
_WINDOW = 70

# Мягкие слова превращают требование в пожелание.
_SOFT = re.compile(r"prefer|ideally|nice\s+to\s+have|\bplus\b|bonus|желательн|"
                   r"приветству|будет\s+плюсом", re.I)

# Всегда блокирует: гражданство, национальность, допуск.
_NATIONALITY = [
    re.compile(r"\bopen\s+(?:exclusively|only)\s+to\b", re.I),
    re.compile(r"\bmust\s+(?:be|hold)\s+(?:a\s+|an\s+)?(?=[\w. ]{1,25}\bcitizen)", re.I),
    re.compile(r"(?:только|исключительно)\s+(?:для\s+)?(?:граждан|резидент|жител)\w*",
               re.I),
    re.compile(r"(?:требуется|обязательно|необходимо|нужно)\s+(?:наличие\s+)?"
               r"гражданств\w*", re.I),
]
# «<страна> citizens only», «US-based candidates only», «Remote (US only)».
_X_ONLY = re.compile(
    r"([A-Za-z][\w.]*(?:\s+[A-Z][\w.]*)?)[-\s]+(?:based\s+)?"
    r"(?:(?:citizens|nationals|residents|candidates|applicants)\s+)?only\b")
_CLEARANCE = re.compile(r"\bsecurity\s+clearance\b|\bgreen\s+card\s+holders?\b", re.I)

# Блокирует, если работодатель не предлагает визу.
_RESIDENCY = [
    re.compile(r"\b(?:must|should|need\s+to|required\s+to|have\s+to)\s+(?:currently\s+)?"
               r"(?:be\s+)?(?:currently\s+)?(?:based|located|residing|reside|living|live)"
               r"\s+(?:in|within)\b", re.I),
    re.compile(r"\b(?:candidates|applicants)\s+(?:must\s+be\s+|should\s+be\s+|need\s+to\s+be\s+)?"
               r"(?:currently\s+)?(?:based|located|residing)\s+(?:in|within)\b", re.I),
    re.compile(r"\b(?:only|exclusively)\s+(?:open\s+to\s+|for\s+|accepting\s+|considering\s+|"
               r"hiring\s+)?(?:candidates|applicants|residents|people|talent)\s+(?:who\s+are\s+)?"
               r"(?:based\s+|located\s+|residing\s+|living\s+)?(?:in|from|within)\b", re.I),
    re.compile(r"\bhires?\s+remotely\s+in\b", re.I),
    re.compile(r"(?:только|исключительно)\s+(?:из|на\s+территории)\b", re.I),
    re.compile(r"(?:обязательн\w*|необходим\w*|требуется)\s+(?:нахождение|находиться|"
               r"проживание|проживать|присутствие)\s+(?:в|на\s+территории)\b", re.I),
]
_AUTHORIZATION = [
    re.compile(r"\b(?:authori[sz]ed|eligible|permitted|legally\s+able|entitled|right)\s+"
               r"to\s+work\s+(?:\w+\s+){0,2}?in\b", re.I),
    re.compile(r"\bwork\s+(?:authori[sz]ation|permit)\s+(?:for|in)\b", re.I),
]

_NO_SPONSOR = re.compile(
    r"\bno\s+(?:visa\s+)?sponsorship"
    r"|sponsorship\s*(?:is\s+|:\s*)?(?:not\s+(?:available|provided|offered|possible)"
    r"|unavailable)"
    r"|(?:unable|not\s+able)\s+to\s+(?:provide|offer|sponsor|support)\s+(?:any\s+)?"
    r"(?:visas?|work\s+(?:visas?|permits?)|sponsorship|h-?1b)"
    r"|(?:cannot|can't|can\s+not|will\s+not|won't|do\s+not|don't|does\s+not|doesn't|"
    r"are\s+not|aren't)\s+(?:currently\s+)?(?:able\s+to\s+)?(?:provide|offer|sponsor|"
    r"support)\s+(?:any\s+)?(?:visas?|work\s+(?:visas?|permits?)|sponsorship|"
    r"employment\s+visas?|h-?1b|immigration)"
    r"|without\s+(?:the\s+need\s+for\s+)?(?:current\s+or\s+future\s+|any\s+)?"
    r"(?:visa\s+|employer\s+)?sponsorship"
    r"|визу\s+не\s+(?:оформляем|спонсируем|делаем)|без\s+(?:визовой\s+поддержки|"
    r"спонсорства)", re.I)
_OFFERS_SPONSOR = re.compile(
    r"(?:visa\s+)?sponsorship\s+(?:is\s+)?(?:available|provided|offered)"
    r"|\b(?:we|will|can)\s+(?:happily\s+)?sponsor\b"
    r"|\b(?:offer|provide)s?\s+(?:full\s+)?(?:visa\s+sponsorship|visa\s+support|"
    r"relocation\s+(?:and|&)\s+visa)"
    r"|visa\s+(?:support|assistance)\s+(?:is\s+)?(?:available|provided|offered)"
    r"|relocation\s+(?:package|support|assistance)?\s*(?:and|&|\+|with)\s+visa"
    r"|visa\s+sponsorship\s+(?:and|&|\+)\s+relocation"
    r"|визов\w+\s+поддержк\w+|помощь\s+с\s+визой|оформляем\s+визу", re.I)
_ANYWHERE = re.compile(
    r"work\s+from\s+anywhere|anywhere\s+in\s+the\s+world|remote\W{0,3}"
    r"(?:worldwide|anywhere|global)|\bworldwide\b|from\s+any\s+country|"
    r"из\s+любой\s+(?:точки|страны)", re.I)


def _sentence_around(text: str, start: int, end: int) -> str:
    before = [m.end() for m in _SENTENCE_END.finditer(text, 0, start)]
    after = _SENTENCE_END.search(text, end)
    return text[before[-1] if before else 0: after.start() if after else len(text)]


def _window_after(text: str, end: int) -> str:
    stop = _SENTENCE_END.search(text, end)
    return text[end: min(stop.start() if stop else len(text), end + _WINDOW)]


def _foreign(places: list[str], neutral: bool, home: str) -> list[str]:
    """Страны, в которые кандидат не проходит. Пусто — если требование выполнимо
    (есть домашняя страна или нейтральный регион) или места не нашлось вовсе."""
    if not places or neutral or home in places:
        return []
    return places


def _quote(text: str, start: int, end: int) -> str:
    return " ".join(_sentence_around(text, start, end).split())[:120]


def check_eligibility(text: str, location: str = "",
                      home_country: str = "Kazakhstan") -> Eligibility:
    """Вердикт по тексту вакансии и её локации; см. докстроку модуля."""
    text = text or ""
    home = _canon(home_country)
    result = Eligibility()
    no_sponsor = _NO_SPONSOR.search(text)
    offers = None if no_sponsor else _OFFERS_SPONSOR.search(text)

    def block(reason: str) -> None:
        if reason not in result.blocking_reasons:
            result.blocking_reasons.append(reason)

    def requirement(patterns, kind: str) -> None:
        for rx in patterns:
            for m in rx.finditer(text):
                if _SOFT.search(_sentence_around(text, m.start(), m.end())):
                    continue
                places, neutral = _places_in(_window_after(text, m.end()))
                bad = _foreign(places, neutral, home)
                if bad:
                    block(f"{kind} {', '.join(bad)} («{_quote(text, m.start(), m.end())}»)")

    requirement(_NATIONALITY, "только для граждан/жителей")
    for m in _X_ONLY.finditer(text):
        if _SOFT.search(_sentence_around(text, m.start(), m.end())):
            continue
        places, neutral = _places_in(m.group(1))
        bad = _foreign(places, neutral, home)
        if bad:
            block(f"только для {', '.join(bad)} («{_quote(text, m.start(), m.end())}»)")
    for m in _CLEARANCE.finditer(text):
        if not _SOFT.search(_sentence_around(text, m.start(), m.end())):
            block(f"нужен допуск/гражданство («{_quote(text, m.start(), m.end())}»)")

    if not offers:
        requirement(_RESIDENCY, "нужно находиться в")
        requirement(_AUTHORIZATION, "нужно право работать в")

    if no_sponsor:
        places, neutral = _places_in(location or "")
        bad = _foreign(places, neutral, home)
        if bad and not _ANYWHERE.search(f"{text}\n{location}"):
            block(f"визу не спонсируют, а работа в {', '.join(bad)} "
                  f"(«{_quote(text, no_sponsor.start(), no_sponsor.end())}»)")
        elif not result.blocking_reasons:
            result.warnings.append("визу не спонсируют — подходит только удалёнка "
                                   "без привязки к стране")

    result.eligible = not result.blocking_reasons
    return result
