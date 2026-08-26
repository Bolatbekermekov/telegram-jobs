"""Deterministic detection of (platform, target) from free vacancy text.

Sender-side copy of the intake bot's rule set. The two apps are separate deploys
with their own requirements, and this project already duplicates domain code
across them on purpose (`sheets_repo.py`, `lead.py`) rather than carrying a shared
package — this follows that.

Used by the Threads resolver: a thread's own text is where the real contact lives
("Для отклика присылайте портфолио в Telegram: @skyluckwalker"), and finding it is
what lets a threads lead be sent through the existing Telegram/email channel.

There is deliberately NO `threads` rule here: by the time this runs the lead is
already threads, and the question is only what it should become instead.

Единственное, чего форма текста не решает, — человек это или канал: строки
неразличимы. Этот один вопрос уходит наружу, в необязательный оракул
`telegram_writable`; отказанный адрес уступает очередь следующему кандидату, а
не следующему правилу.

Priority order: telegram > email > linkedin > hh > wellfound. Rule-based on
purpose: it decides where the message is sent, so it must not be an LLM guess.
"""
import re
from dataclasses import dataclass


@dataclass
class Contact:
    platform: str   # telegram | email | linkedin | hh | wellfound
    target: str     # @nick / t.me URL / email / profile or vacancy URL


_TME_RE = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/\w{3,}", re.IGNORECASE)

# Служебные пути t.me: за ними стоит не человек, а функция мессенджера. Замер
# листа 2026-08-26: лиды #435 и #436 получили целью `https://t.me/addlist` —
# ссылку на ПАПКУ ЧАТОВ, которой подписывают пост. Отправка в неё не может
# состояться, а настоящая почта работодателя из того же поста терялась, потому
# что правило t.me стоит первым.
#
# Отсекаются по имени, а не оракулом: оракул доказывает только отказ («это
# канал»), а на служебный путь Bot API отвечает «chat not found» — тем же, чем
# на живого человека, которого бот не видит.
_TME_RESERVED = frozenset({
    "addlist", "joinchat", "share", "proxy", "socks", "iv", "login",
    "addstickers", "addemoji", "addtheme", "setlanguage", "confirmphone",
    "invoice", "giftcode", "boost", "contact", "bg",
})


def _is_service_path(target: str) -> bool:
    """Первый сегмент пути t.me — служебный, а не имя пользователя."""
    tail = target.rstrip("/").rsplit("/", 1)[-1] if "/" in target else ""
    return tail.split("?", 1)[0].lower() in _TME_RESERVED

# A Telegram @handle anchored to start-or-whitespace, so it never matches the
# "@" inside an email address (e.g. john@gmail.com). That anchor is the only thing
# keeping a well-formed email out of this rule, which is second of six and so
# pre-empts email/linkedin/hh whenever it fires.
# Allowing a space after the at-sign (`@\s?`, for the "@ skyluckwalker" seen on a
# live Threads post) was tried here and reverted: it also matches the "at" of
# "hr @ acme.com" and "Role @ Company", fabricating an "@acme"/"@Company" target
# while the real contact sat later in the same text.
# Threads' own LINKIFIED mentions do reach this rule glued, and that is built and
# verified against the live page: the DOM reader unwraps the mention anchor before
# reading the text (infrastructure/threads_thread.py), which is what stops innerText
# tearing "@nick" onto a line of its own.
# An at-sign the AUTHOR typed with a space after it is a different thing and is NOT
# covered. Measured 2026-07-26: that space is in the post as Threads stores it
# (its own payload has linkified_in_app_url: null precisely because of it), so no
# reader-side fix exists — the DOM is faithful, there is nothing to unglue. Closing
# it needs a TEXT-level rule, and the only safe shape is a contextual one applied in
# the resolver — glue "@ nick" only where a telegram/тг cue sits just before it —
# never a blanket `@\s+` here, which is the revert above. That rule is deliberately
# unwritten pending a human decision, so such a handle stays undetected and
# _HANDLE_RE stays an exact copy of the intake's.
_HANDLE_RE = re.compile(r"(?:^|\s)@(\w{4,})\b")
# The capture above is `\w{4,}` and stops at the first dot, so "@maria.hr" arrives at
# the rule as "@maria" — a different, real user. This reads the whole HANDLE-SHAPED
# head at a match position instead, which is what the rule needs to see to refuse it.
# Dots are legal in a Threads/Instagram handle (that namespace is Instagram's) and
# illegal in a Telegram username, which is the whole basis for refusing.
# The charset is what decides where a handle ends, and it is ASCII — letters, digits,
# periods, underscores — so the first non-ASCII character ENDS the handle: "@ivan.Пиши"
# heads "ivan.", i.e. a plain "@ivan" followed by a sentence, not a dotted handle.
# `*`, not `+`, because `\w` matches Cyrillic too: "@Иван_Петров" has an EMPTY ASCII
# head, and `+` would fail to match there and raise on `.group(0)`.
_ASCII_HANDLE_RE = re.compile(r"[A-Za-z0-9._]*")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_LINKEDIN_RE = re.compile(r"(?:https?://)?(?:www\.)?linkedin\.com/\S+", re.IGNORECASE)
_HH_HOST = r"(?:[\w.-]*\.)?hh\.(?:ru|kz|uz|by|kg|az|tj)"
# A vacancy link is matched first and separately: the iOS share sheet sends
#   "Vacancy: https://hh.kz/vacancy/135297431  … Sent via hh mobile app https://hh.ru/mobile"
# so a rule that takes any hh link would store the app-download footer as the target.
_HH_VACANCY_RE = re.compile(rf"(?:https?://)?{_HH_HOST}/vacancy/\d+\S*", re.IGNORECASE)
_HH_RE = re.compile(rf"(?:https?://)?{_HH_HOST}/\S+", re.IGNORECASE)
_WELLFOUND_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:wellfound\.com|angel\.co)/\S+", re.IGNORECASE)

_TRAILING = ".,);]>\"'"


def _clean(url: str) -> str:
    return url.rstrip(_TRAILING)


_HH_VACANCY_ID_RE = re.compile(rf"^(?:https?://)?{_HH_HOST}/vacancy/(\d+)", re.IGNORECASE)
_HH_REGIONAL_RE = re.compile(
    r"^(?:https?://)?(?:[\w.-]*\.)?hh\.(?:kz|uz|by|kg|az|tj)/", re.IGNORECASE)


def canonical_hh_url(url: str) -> str:
    """A regional HeadHunter link -> the hh.ru URL the saved session can open.

    Kept in this copy on purpose: the browser session from `make login_hh` is
    hh.ru-only, cookies don't cross to a national domain, so a regional link
    browses anonymously and dead-ends at the login wall on Apply. A thread that
    says "откликнуться на hh.kz/vacancy/…" would walk straight into that.
    """
    m = _HH_VACANCY_ID_RE.match(url)
    if m:
        return f"https://hh.ru/vacancy/{m.group(1)}"
    return _HH_REGIONAL_RE.sub("https://hh.ru/", url, count=1)


# A scheme is optional in every rule above, because that is how links arrive: a
# phone paste and Telegram's own link text both drop it. The siblings put it back
# — hh through `canonical_hh_url`, Threads through `canonical_threads_url` — and
# this rule did not, so `linkedin.com/jobs/view/…` was stored as the contact
# verbatim. Every predicate in vacancy_text anchors on `^https?://`, so that lead
# was not a candidate for the vacancy read at all: nothing fetched the page, and
# «Вакансия» was filled by the summariser explaining it cannot open links. Same
# class of miss as the slug shape (lead #169), one layer earlier.
_SCHEME_RE = re.compile(r"^https?://", re.IGNORECASE)


_LINKEDIN_APEX_RE = re.compile(r"^https?://linkedin\.com/", re.IGNORECASE)


def canonical_linkedin_url(url: str) -> str:
    """A LinkedIn link -> one the fetcher can actually open.

    The host matters as much as the scheme, and it is not cosmetic. Measured live
    2026-08-22 on the same job: `www.linkedin.com/jobs/view/…` answers 200 with the
    whole 247 KB job page, while the apex `linkedin.com/jobs/view/…` answers 200
    with a 20 KB shell that carries no advert at all. Both are "200", so nothing
    downstream could tell them apart — the read just came back empty. Subdomains
    other than the apex are left as written: they were not measured, and a guess
    here is a silently empty read.
    """
    if not _SCHEME_RE.match(url):
        url = f"https://{url}"
    return _LINKEDIN_APEX_RE.sub("https://www.linkedin.com/", url, count=1)


# --- агрегаторы вакансий и RemoteOK ------------------------------------------
# Пост со ссылкой на доску вакансий раньше терялся целиком: ни одно правило выше
# такую ссылку не узнавало, detect_contact отвечал None, и бот говорил
# «Не нашёл контакт», ничего не сохранив. Проверено живьём 2026-08-22 на трёх
# формах сообщения — голая ссылка, пост без контакта, пост с @ником.
#
# RemoteOK держится ОТДЕЛЬНОЙ площадкой, а не на площадке Remocate, потому что у
# него в sender'е свой канал: переход через /l/<id> со страницы вакансии (без
# Referer этот путь отвечает 302 обратно) и распознавание платной Premium-стены.
# Общий путь для агрегаторов это потерял бы.
# Площадка называется по агрегатору: имя попадает в таблицу, и «external»
# там не сообщало ни откуда вакансия, ни есть ли под неё автоматизация.
# Драйвер в отправителе общий на все агрегаторы — различает их имя.
_AGGREGATOR_RE = re.compile(
    r"(?:https?://)?(?:www\.)?remocate\.app/jobs/[\w%-]+\S*", re.IGNORECASE)
_REMOTEOK_RE = re.compile(
    r"(?:https?://)?(?:www\.)?remoteok\.com/remote-jobs/[\w%-]+\S*", re.IGNORECASE)


def _with_scheme(url: str) -> str:
    """Схема обязательна: без неё это не адрес, который откроет браузер."""
    return url if _SCHEME_RE.match(url) else f"https://{url}"


def _writable(target: str, ask) -> bool:
    """Можно ли вообще писать по этому телеграм-адресу. Копия интейковой.

    Форма ника ничего не говорит: «@simbirsoft_dev» и «@ivan_hr» неразличимы как
    строки, а первый — канал, куда Telethon отвечает «You can't write in this
    chat». Отказ засчитывается только на явное False; «не знаю» и сломанный
    оракул — в пользу лида.
    """
    if ask is None:
        return True
    try:
        return ask(target) is not False
    except Exception:  # noqa: BLE001 — лид дороже идеальной маршрутизации
        return True


def detect_contact(text: str, telegram_writable=None) -> Contact | None:
    """(площадка, адрес) из текста треда, или None.

    `telegram_writable(target) -> bool | None` — тот же необязательный оракул
    «человек, а не канал», что и у интейка; здесь его подключает резолвер тредов
    (`application/resolve_threads.py`).
    """
    # Каждая ссылка, а не только первая: подпись канала-агрегатора стоит в КОНЦЕ
    # поста и всё равно выигрывала у почты работодателя. Отклонённая ссылка
    # передаёт очередь следующей, а не всему правилу сразу.
    for m in _TME_RE.finditer(text):
        target = _clean(m.group(0))
        if _is_service_path(target):
            continue
        if _writable(target, telegram_writable):
            return Contact("telegram", target)
    for m in _HANDLE_RE.finditer(text):
        # A Telegram username cannot contain a dot, so "@maria.hr" is provably not a
        # Telegram target — it is an Instagram/Threads handle. _HANDLE_RE captures
        # `\w{4,}` and stops at the dot, so returning the match would store "@maria":
        # a real, unrelated user nobody wrote in the thread. Refuse the whole handle
        # and keep going — hence `finditer`, so a real handle later in the same text
        # still wins. If nothing else answers, the lead keeps its Threads DM fallback,
        # which is weak but at least reaches the person who actually posted.
        #
        # WHICH dot counts is decided by what follows it, and that is not a nicety.
        # A handle continues only in the ASCII charset Instagram/Threads uses, so a
        # dot followed by non-ASCII cannot be a handle carrying on — it is a period
        # whose space the writer forgot. "пиши @ivan.Пиши в личку" is therefore an
        # ordinary "@ivan" and still wins, while "@maria.hr" is refused: the rule
        # rejects exactly the shape that is provably not Telegram, and nothing else.
        # A TRAILING dot is sentence punctuation ("пиши @ivan.") and is stripped
        # before the test, so that shape is a plain handle and wins too.
        #
        # The intake's author exemption has no counterpart here on purpose: there is
        # no Threads rule and no post URL in this copy, so it never had an author to
        # exempt. Refusing dotted handles is NOT part of that exemption and must stay
        # mirrored — it is the same rule in both apps.
        handle = _ASCII_HANDLE_RE.match(text, m.start(1)).group(0).rstrip(".")
        if "." in handle:
            continue
        # Кириллица внутри ника — тот же класс доказуемой подделки, что и точка.
        # Telegram сам назвал спецификацию, когда лид #289 упал: «it must match
        # r"[a-zA-Z][\w\d]{3,30}[a-zA-Z\d]"». `\w` в Python матчит кириллицу,
        # поэтому «@andrеinikolenko» с кириллической «е» побеждал настоящий
        # «@andreinikolenko» строкой ниже. Сравнение ASCII-головы с полным
        # захватом ловит любую примесь. Отказ, а не обрезка: голова «andr» —
        # живой чужой ник, ровно как «@maria» из «@maria.hr».
        if handle != m.group(1):
            continue
        # Ник канала — тоже законный ник, и подписи идут парами («@best_itjob /
        # @it_rab»), поэтому проверка внутри цикла: отказ уступает очередь
        # следующему нику, а если человеческого нет — почте ниже.
        target = "@" + m.group(1)
        if _writable(target, telegram_writable):
            return Contact("telegram", target)
    m = _EMAIL_RE.search(text)
    if m:
        # `_clean` like every sibling rule: _EMAIL_RE's tail class `[\w.-]+` eats the
        # period that ended the sentence, and "hr@acme.io." is what an MTA rejects at
        # RCPT TO — the lead lands `failed` and the recruiter is never written to.
        return Contact("email", _clean(m.group(0)))
    m = _LINKEDIN_RE.search(text)
    if m:
        return Contact("linkedin", canonical_linkedin_url(_clean(m.group(0))))
    m = _HH_VACANCY_RE.search(text) or _HH_RE.search(text)
    if m:
        return Contact("hh", canonical_hh_url(_clean(m.group(0))))
    m = _WELLFOUND_RE.search(text)
    if m:
        return Contact("wellfound", _clean(m.group(0)))
    m = _AGGREGATOR_RE.search(text)
    if m:
        return Contact("remocate", _with_scheme(_clean(m.group(0))))
    m = _REMOTEOK_RE.search(text)
    if m:
        return Contact("remoteok", _with_scheme(_clean(m.group(0))))
    return None
