"""Deterministic detection of (platform, target) from free vacancy text.

Priority order: telegram > email > linkedin > hh > wellfound > threads. The first
rule that matches wins. Platform detection is rule-based on purpose: it decides
where the message is later sent, so it must not depend on an LLM guess.

The one thing the rules cannot decide from the text is whether a telegram target
is a PERSON or a CHANNEL — the two are the same string shape — so that single
question is asked of Telegram itself through the optional `telegram_writable`
oracle. A refused target yields to the next candidate, not to the next rule.

Threads is deliberately last: a recruiter who drops a thread link next to their own
@nick or e-mail is reachable there directly, and a direct channel beats a public
post. Only the post author's own handle is exempt (see detect_contact).
"""
import re
from dataclasses import dataclass


@dataclass
class Contact:
    platform: str   # telegram | email | linkedin | hh | wellfound | threads
    target: str     # @nick / t.me URL / email / profile or vacancy URL


# t.me / telegram.me links (scheme optional).
_TME_RE = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/\w{3,}", re.IGNORECASE)
# A Telegram @handle anchored to start-or-whitespace, so it never matches the
# "@" inside an email address (e.g. john@gmail.com).
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
# HeadHunter runs one network across national domains (hh.kz, hh.uz, …) and the
# regional subdomains under them (astana.hh.kz). Vacancy ids are shared network-wide.
_HH_HOST = r"(?:[\w.-]*\.)?hh\.(?:ru|kz|uz|by|kg|az|tj)"
# A vacancy link is matched first and separately: the iOS share sheet sends
#   "Vacancy: https://hh.kz/vacancy/135297431  … Sent via hh mobile app https://hh.ru/mobile"
# so a rule that takes any hh link would store the app-download footer as the target.
_HH_VACANCY_RE = re.compile(rf"(?:https?://)?{_HH_HOST}/vacancy/\d+\S*", re.IGNORECASE)
_HH_RE = re.compile(rf"(?:https?://)?{_HH_HOST}/\S+", re.IGNORECASE)
_WELLFOUND_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:wellfound\.com|angel\.co)/\S+", re.IGNORECASE)

# Threads (Meta). Posts live at /@user/post/<id>. threads.net is an alias that
# 301s to threads.com (verified 2026-07-26: identical bytes), so it is folded onto
# .com — the sender opens exactly what the sheet holds. The iOS/Android share sheet
# appends a tracking blob (?xmt=…&slof=1) that is noise for us. The left boundary
# keeps the host from matching inside a look-alike one (notthreads.com), which would
# otherwise be canonicalised into a threads.com URL nobody ever sent.
_THREADS_HOST = r"(?:www\.)?threads\.(?:com|net)"
_THREADS_RE = re.compile(
    rf"(?<![\w.-])(?:https?://)?{_THREADS_HOST}/@[\w.]+/post/[\w-]+\S*", re.IGNORECASE)
_THREADS_PARTS_RE = re.compile(
    rf"^(?:https?://)?{_THREADS_HOST}/@([\w.]+)/post/([\w-]+)", re.IGNORECASE)


def canonical_threads_url(url: str) -> str:
    """A shared Threads link -> the plain post URL the sender can open."""
    m = _THREADS_PARTS_RE.match(url)
    if not m:
        return url
    return f"https://www.threads.com/@{m.group(1)}/post/{m.group(2)}"


def threads_author(url: str) -> str:
    """'@handle' of the post author from the URL, or '' when it is not a Threads
    post link. Authoritative author comes from the rendered page in the sender;
    this is what the intake has to work with."""
    m = _THREADS_PARTS_RE.match(url)
    return "@" + m.group(1) if m else ""


_TRAILING = ".,);]>\"'"


def _clean(url: str) -> str:
    return url.rstrip(_TRAILING)


# Vacancy id out of any HeadHunter link: national domain, regional subdomain, and
# whatever tracking the sharer appended.
_HH_VACANCY_ID_RE = re.compile(rf"^(?:https?://)?{_HH_HOST}/vacancy/(\d+)", re.IGNORECASE)
_HH_REGIONAL_RE = re.compile(
    r"^(?:https?://)?(?:[\w.-]*\.)?hh\.(?:kz|uz|by|kg|az|tj)/", re.IGNORECASE)


def canonical_hh_url(url: str) -> str:
    """A shared HeadHunter link -> the plain desktop URL the sender can open.

    Phone shares arrive as `https://astana.hh.kz/vacancy/135297431?from=share_ios`.
    Two things are wrong with that for us: the tracking tail is noise, and the
    browser session from `make login_hh` is hh.ru-only — cookies don't cross to a
    national domain, so a regional link browses anonymously and dead-ends at the
    login wall on Apply. Vacancy ids are shared across the whole network, so the
    same id on hh.ru is the same vacancy, opened logged in.
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
    """Можно ли вообще писать по этому телеграм-адресу.

    Форма ника ничего не говорит: «@simbirsoft_dev» и «@ivan_hr» неразличимы как
    строки, а первый — канал, куда отправка отвечает «You can't write in this
    chat». Знает об этом только сам Telegram, поэтому вопрос задаётся наружу, а
    правило остаётся чистым: без `ask` эта функция всегда отвечает «да» и
    маршрутизация ровно та же, что была.

    Отказ засчитывается ТОЛЬКО на явное False. «Не знаю» (None) и сломанный
    оракул — в пользу лида: Bot API отвечает «chat not found» и живому человеку,
    и несуществующему нику, так что молчание не доказывает ничего, а недоступный
    Telegram не повод выбросить контакт.
    """
    if ask is None:
        return True
    try:
        return ask(target) is not False
    except Exception:  # noqa: BLE001 — см. докстроку: лид дороже маршрутизации
        return True


def detect_contact(text: str, telegram_writable=None) -> Contact | None:
    """(площадка, адрес) из текста вакансии, или None.

    `telegram_writable(target) -> bool | None` — необязательный оракул «это
    человек, а не канал/группа», см. `_writable`. Живьём его подключает
    `api/webhook.py` через Bot API; тесты и все чистые вызовы обходятся без него.
    """
    # The Threads link is located up front, but only to protect its author handle:
    # "вакансия от @lnkrnchk <threads link>" would otherwise match _HANDLE_RE and
    # be stored as a Telegram contact, and the send loop would DM a user that does
    # not exist there. A DIFFERENT @handle still wins, as it always did — and every
    # handle is scanned, not just the first, because the message may credit the author
    # before it gives the real contact ("вакансия от @lnkrnchk, пиши @ivan_hr") just
    # as easily as after it. Only a message whose every handle is the author falls
    # through to threads.
    tm = _THREADS_RE.search(text)
    threads_url = canonical_threads_url(_clean(tm.group(0))) if tm else ""
    author = threads_author(threads_url).lower()

    # Каждая ссылка, а не только первая: подпись канала-агрегатора («IT Jobs в
    # Telegram | VK | Max» со ссылкой на себя) стоит в КОНЦЕ поста и всё равно
    # выигрывала у почты работодателя, потому что telegram — первое правило.
    # Отклонённая ссылка передаёт очередь следующей, а не всему правилу сразу.
    for m in _TME_RE.finditer(text):
        target = _clean(m.group(0))
        if _writable(target, telegram_writable):
            return Contact("telegram", target)
    for m in _HANDLE_RE.finditer(text):
        # A Telegram username cannot contain a dot, so "@maria.hr" is provably not a
        # Telegram target — it is an Instagram/Threads handle. _HANDLE_RE captures
        # `\w{4,}` and stops at the dot, so returning the match would store "@maria":
        # a real, unrelated user nobody wrote in the message. Refuse the whole handle
        # and keep going. If no other handle and no other rule answers, the intake
        # replies «⚠️ Не нашёл контакт» and asks for a resend, which is honest; a
        # truncated stranger is not.
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
        # This is the general form of the author leak closed earlier, and it subsumes
        # it for every dotted shape — "@ivan.hr", "@lnkrnchk.hr", "@ivan.hr.Пиши" are
        # refused for everyone, author or not — so the three author clauses that used
        # to sit here collapse into the one below.
        handle = _ASCII_HANDLE_RE.match(text, m.start(1)).group(0).rstrip(".")
        if "." in handle:
            continue
        # Кириллица внутри ника — тот же класс доказуемой подделки, что и точка.
        # Telegram сам назвал спецификацию, когда лид #289 упал: «it must match
        # r"[a-zA-Z][\w\d]{3,30}[a-zA-Z\d]"». В посте стояло «@andrеinikolenko» с
        # кириллической «е» посередине, а настоящий «@andreinikolenko» латиницей —
        # двумя строками ниже; `\w` в Python матчит кириллицу, поэтому побеждала
        # подделка. Сравнение ASCII-головы с полным захватом ловит любую примесь.
        #
        # Отказ, а не обрезка до головы: у #289 голова — «andr», живой чужой ник.
        # Ровно причина, по которой «@maria.hr» не превращается в «@maria».
        if handle != m.group(1):
            continue
        # What is left is an UNDOTTED author, who is a valid Telegram shape and would
        # otherwise be DMed at a handle that does not exist there. Compared on the
        # handle head rather than on the capture, and that is load-bearing in both
        # directions: "@lnkrnchk.Пиши" reduces to "lnkrnchk" — the author, who must
        # not leak — while a bare prefix test would swallow "@lnkrnchk_hr", who is a
        # different person and a real contact.
        if author and handle.lower() == author[1:]:
            continue
        # Ник канала — тоже законный ник, и лид #87 держал сразу два подряд
        # («Подписаться на наши каналы / @best_itjob / @it_rab»), поэтому
        # проверка стоит внутри цикла: отказ уступает очередь следующему нику, а
        # если человеческого нет — почте ниже.
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
    if threads_url:
        return Contact("threads", threads_url)
    return None
