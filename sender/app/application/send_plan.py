"""Per-lead gating for the id-order send loop.

Leads are sent in sheet order (by id). Before opening a channel for a lead we
ask skip_reason() whether it should be skipped — so a skip never causes a
channel switch. Only an unknown platform qualifies: channel-start failures and
mid-run rate limits are handled by the loop itself, which leaves those leads
`new` rather than writing a terminal status.
"""
import re

from app.domain.lead import STATUS_MANUAL, STATUS_SKIPPED
from app.domain.page_gone import GONE_NOTE
from app.domain.vacancy_text import (
    is_aggregator_job_url, is_hh_vacancy_url, is_linkedin_job_url,
    is_remoteok_job_url,
)
from app.infrastructure.channels.threads import normalize_target
from app.infrastructure.threads_thread import author_from_url


def skip_reason(lead, known) -> tuple[str, str] | None:
    """Why this lead can't be sent right now, as (status, note), or None to send.

    Only an unknown platform is a per-lead skip. Two other failures are handled
    in the send loop instead: a channel that won't start stops the whole run
    (the lead was never attempted, so it stays `new`), and a platform that
    rate-limited us mid-run leaves its remaining leads `new` for the next run.
    """
    p = lead.platform
    if p not in known:
        return (STATUS_SKIPPED, f"unknown platform: {p}")
    if not (lead.target or "").strip():
        # No address at all. Every channel would fail on this, but LinkedIn failed
        # the worst: `linkedin_action_for_url("")` reads an empty string as a
        # profile DM, so the channel ran `page.goto("")` and the lead landed in
        # `failed` carrying "Protocol error (Page.navigate): Cannot navigate to
        # invalid URL" — a Playwright internal, not something a human can act on
        # (lead #93). `manual`, not `skipped`: a blank «Источник» is fixed by hand
        # in the sheet, and no number of re-runs will fill it in.
        return (STATUS_MANUAL, "пустой «Источник» — впиши адрес в таблицу вручную")
    return None


def hold_reason(auto_send: bool, review: str = "", contact: str = "",
                source_url: str = "") -> tuple[str, str] | None:
    """Why an unattended run must not send this lead, as (status, note), or None.

    `review` is the resolver's verdict on the contact — non-empty when a human has
    to look before it goes out, and already phrased for a human (see
    `resolve_threads_lead.REVIEW_MODEL`). Auto mode has no
    confirmation step, so a contact nobody has read must not be sent; interactive
    runs show the same reason and let the human decide.

    The status is `manual`, not `new`. `new` does not survive here: by this point
    the row has already been rewritten to an ordinary platform, so the next run
    would find a normal lead, resolve nothing, raise no flag and auto-send it
    unread — the hold would last exactly one run. `manual` is outside
    `fetch_new_leads`, it says the truth ("needs a person"), and it is not the
    terminal `skipped` the human forbade. The cost: getting such a lead back into
    the queue means setting Статус to `new` in the sheet by hand, because nothing
    in the sender writes that value to an existing row.

    Deliberately NOT the same treatment as `has_placeholder` below: a contact is
    decided once and sticks, a message body is regenerated from scratch every run.

    The note carries what acting by hand needs — why it stopped, what it would
    have been sent to, and where that came from — because the row itself only
    shows where the lead now points.
    """
    if not auto_send or not review:
        return None
    parts = [review]
    if contact:
        parts.append(f"контакт: {contact}")
    if source_url:
        parts.append(f"тред: {source_url}")
    return STATUS_MANUAL, "; ".join(parts)


# What an answer at the interactive confirmation prompt means. Pure, and out here
# rather than inline in the loop, so the one rule that matters can be pinned by a
# test: nothing but an explicit "s" sends.
CONFIRM_SEND = "send"
CONFIRM_SKIP = "skip"
CONFIRM_QUIT = "quit"
CONFIRM_HOLD = "hold"


def confirm_action(choice: str) -> str:
    """Read one confirmation answer. Sends ONLY on an explicit s/send.

    The loop used to handle k/skip and q/quit and let everything else fall through
    into `sender.execute`. Everything else is a lot: `e` and `r`, which the README
    documented until two commits ago; any typo; and a bare Enter — the exact reflex
    after the «Остался [плейсхолдер]» warning printed one line above the prompt,
    which is what makes a user reach for a key in the first place.

    It compounds off-screen. `_prompt` answers `EOFError` with "", so `make run` on a
    non-TTY stdin (cron, a pipe, an editor's run button) walked the whole queue
    sending everything — unattended, and WITHOUT the placeholder gate, which only
    runs under AUTO_SEND. Auto mode is a deliberate switch; inheriting it from a
    closed stdin is not.

    `hold` — anything unrecognised — writes no status: the lead stays `new` and the
    next run offers it again, the same self-healing the placeholder and
    generation-failure paths already rely on. Deliberately NOT `skip`, which is
    terminal, and deliberately not a re-prompt: "" is what a closed stdin returns
    forever, so a loop asking again would spin.
    """
    c = (choice or "").strip().lower()
    if c in ("s", "send"):
        return CONFIRM_SEND
    if c in ("k", "skip"):
        return CONFIRM_SKIP
    if c in ("q", "quit"):
        return CONFIRM_QUIT
    return CONFIRM_HOLD


def unresolved_thread(target: str) -> bool:
    """True when the lead still points at a thread POST rather than at a person.

    Asked of the target's SHAPE, deliberately, and of nothing else. `author_from_url`
    accepts only a `…/@handle/post/<id>` URL, so a target it recognises is a thread
    nobody has read yet, and a target it rejects — `@hr_acme` — is somebody to write
    to. No history is inferred and no second value is consulted.

    That matters, because the obvious formulation is wrong. Deriving "the resolver
    never ran" from `target == source_url` holds for a thread that failed to render,
    but ALSO for a lead already resolved onto the DM fallback and re-queued by hand:
    its row holds Источник=@hr_acme, `render` refuses that (it is not a post URL),
    `resolve_threads_lead` hands the lead back untouched, and the identity is true a
    second time — so the lead read as "never rendered", was skipped with no status,
    and sat `new` forever. That is exactly the recovery this feature promises: the
    gate note tells the human to run `make login_threads` and put Статус back to
    `new`, and nothing would have happened when they did.

    Two callers need this and must agree, hence one definition:
      * `dm_fallback_reason` — a lead with nobody to write to is not a DM-fallback
        lead, so the no-session gate must not park it as `manual`;
      * the send loop — which must `continue` on it instead of falling through to
        the channel. Falling through is not harmless: with no session
        `ThreadsChannel.start()` raises `ChannelUnavailable`, which the loop answers
        with `SystemExit(1)`, killing the run for every other platform too; with a
        session it would DM the author off the root post alone, without the vacancy
        text and the contact the unread self-replies were supposed to carry.

    A thread that never renders is therefore retried every run and never sent, which
    is visible in the sheet as a Threads row that keeps coming back `new`.
    """
    return bool(author_from_url(target))


def dm_fallback_reason(platform: str, session_live, author: str = "",
                       source_url: str = "") -> tuple[str, str] | None:
    """Why the Threads DM fallback can't even be attempted, as (status, note), or None.

    Only ever true of a lead the resolver actually put on the DM fallback: its thread
    was read, named no contact at all, and so the lead stayed on `threads` pointing at
    its author — the weakest route in the feature and the one everything else is built
    to avoid needing.

    Checked BEFORE the channel is opened, which is the whole point. `ThreadsChannel.
    start()` answers a dead session with `ChannelUnavailable`, and the send loop
    answers that with `SystemExit(1)` — right for a channel that is supposed to work
    (a broken session must not go unnoticed while the healthy platforms drain), wrong
    for this one, where "no session" is the expected state until a burner Instagram
    exists and possibly forever, since the human may decide never to create one. One
    contactless Threads lead must not take Telegram, hh and every other platform's
    leads down with it.

    `author` is `lead.target` after resolving. When it is still a thread post URL the
    resolve did NOT happen — `render` failed (login wall, timeout, network blip, all
    expected) and `resolve_threads_lead` handed the lead back untouched, deliberately,
    so that it stays `new` and the next run tries again. That lead is not on the DM
    fallback and must not be gated: parking it as `manual` would forfeit the retry
    and, with it, the better outcome behind the retry — the next render may find a
    real contact in a self-reply and send over Telegram, never touching this channel
    at all. See `unresolved_thread` for why that is a question about shape and not
    about identity with `source_url`.

    A target that is neither a post URL nor a usable handle — a blank Источник, a
    note to self, two handles in one cell — is answered HERE too, and before the
    session is consulted, so that a broken row gets ONE answer instead of two. It
    used to get two: `manual` with no session (this gate fired) and `failed` with
    one (the gate passed, the channel opened and `ThreadsChannel.send` raised on the
    unparseable handle). The row is identical in both runs; only whether a burner
    Instagram exists differed, which is nothing to do with the row. `failed` was
    also the wrong word for a human triaging the sheet — it reads as "the platform
    hiccuped, it'll retry", and retrying a malformed cell never helps. `manual` is
    the feature's parking status: you have to do something.

    `session_live() -> bool` is a callable, not a bool, and is consulted last, so no
    lead that is not on the DM fallback reads the Threads state file at all.

    The status is `manual`, for the same reason `hold_reason` uses it: it is outside
    `fetch_new_leads`, it says the truth ("needs a person"), and it is not the
    terminal `skipped` the human forbade. `new` would be worse than useless HERE —
    unlike the unresolved case above, nothing about the next run is different, so the
    lead would hit the same wall every time, silently, forever.

    The note carries both ways out, because there are genuinely two: log in, or send
    it yourself. `author` is what the row's Источник now holds, and `source_url` the
    thread it came from — which is why the URL goes in, exactly as `hold_reason` does
    it: by the time this writes, `update_resolved` has replaced Источник with the
    handle and `mark_status` is about to overwrite Заметка, which held «…DM автору:
    <URL>». Without it the human is told to write to a handle by hand with no way
    left to open the post and read what the vacancy is.
    """
    if platform != "threads":
        return None
    if unresolved_thread(author):
        return None                      # nobody to write to — still `new`, retried
    if not normalize_target(author):
        # Asked AFTER `unresolved_thread`, which is load-bearing: `normalize_target`
        # happily pulls the author out of a post URL, so asking it first would park
        # every thread that failed to render as `manual` and forfeit its retry.
        parts = ["Источник не похож на хендл Threads — отправить нечего",
                 "впиши контакт вручную и верни Статус в 'new'"]
        if source_url and source_url != author:
            parts.append(f"тред: {source_url}")
        return STATUS_MANUAL, "; ".join(parts)
    if session_live():
        return None
    # `author` is necessarily non-empty here: `normalize_target("")` is "", so a blank
    # Источник left above as a broken row. Both routes out are therefore always real.
    parts = ["сессии Threads нет — DM автору отправить нечем",
             "выполни `make login_threads` на отдельном (burner) Instagram",
             f"или напиши автору вручную: {author}"]
    if source_url and source_url != author:
        # On a re-queued lead the source IS the handle; appending it would add
        # nothing and read as a broken link.
        parts.append(f"тред: {source_url}")
    return STATUS_MANUAL, "; ".join(parts)


def _points_at_a_vacancy_page(target: str) -> bool:
    """Цель лида — адрес объявления, которое можно открыть и спросить.

    Спрашивать есть смысл далеко не у всех. У `telegram` цель — ник, у `email` —
    адрес: там открывать нечего. У профиля и поста в LinkedIn цель — ЧЕЛОВЕК:
    пост могли удалить, а написать автору всё равно можно, и хоронить такой лид
    нельзя. Осмысленно ровно там, где цель и есть страница, на которой мы
    собираемся откликаться, — тогда «страницы нет» означает «делать нечего».

    Собрано из уже существующих предикатов, а не из нового правила: это те же
    четыре формы адреса, которые проект и так умеет читать (`vacancy_text`), и
    заводить им пятое определение значило бы завести пятое место для расхождения.
    """
    t = (target or "").strip()
    return (is_aggregator_job_url(t) or is_remoteok_job_url(t)
            or is_hh_vacancy_url(t) or is_linkedin_job_url(t))


def dead_vacancy_reason(target: str, gone) -> tuple[str, str] | None:
    """Почему на этот лид не стоит тратить генерацию, как (статус, заметка), или None.

    Замер прогона 2026-08-26 по `remocate`: из двенадцати лидов четыре вели на
    закрытые вакансии, и порядок в логе был «Генерирую сообщение...», а следом
    «страница недоступна / вакансия неактуальна». Треть лидов площадки платила
    за письмо, роль и тему объявлению, которого больше нет.

    `gone(url) -> str` возвращает адрес страницы, доказавшей смерть, или "" —
    сеть живёт в инфраструктуре (`vacancy_alive.vacancy_gone`), сюда приходит
    callable, ровно как `session_live` в `dm_fallback_reason`. Пустая строка
    означает «не знаю» и ведёт себя как «жива»: недоступный на секунду сайт —
    не повод хоронить лид.

    Статус — `manual`, и по тем же трём причинам, что у `hold_reason`: он вне
    `fetch_new_leads`, он говорит правду («нужен человек») и он НЕ терминальный
    `skipped`, который владелец запретил проставлять автоматом — закрытый
    автоматом лид человек больше не увидит. Ровно этот статус канал уже пишет,
    когда сам натыкается на снятую вакансию; заметка тоже та же, слово в слово,
    чтобы в листе одна находка называлась одинаково независимо от того, кто её
    сделал — проверка до генерации или браузер после неё.
    """
    if not _points_at_a_vacancy_page(target):
        return None
    dead_url = gone(target)
    if not dead_url:
        return None
    return STATUS_MANUAL, f"{GONE_NOTE}: {dead_url}"


# A slot the writer was supposed to fill: bracketed prose in ANY case
# ("[название компании]", "[Название компании]", "[Your name]",
# "[ПОЧЕМУ ИМЕННО ЭТА КОМПАНИЯ]").
#
# IGNORECASE is load-bearing, not tidiness. A lower-case-only rule was tried and
# it is what let the last three of those through: a model writing a Russian cover
# letter capitalises a bracketed slot opening a sentence essentially always, so
# the common shape was the one the net missed, and README's [!CAUTION] promise
# that auto mode never sends a message with a placeholder in it was false.
# The price of widening — a bracketed proper noun the letter legitimately quotes,
# "вакансию [Senior Dev]" — is one free regeneration, because `has_placeholder`
# writes NO status (see below). A false negative is a template in a recruiter's
# inbox. The two costs are not comparable, so the net stays wide.
_PLACEHOLDER_RE = re.compile(r"\[\s*[a-zа-яё][^\]\n]*\]", re.IGNORECASE)


def has_placeholder(body: str) -> bool:
    """True when the generator left a `[плейсхолдер]` in the message.

    Unlike `hold_reason`, the caller writes NO status for this: the body is a
    per-generation artifact, `generate_body` runs fresh on every run, so leaving
    the lead `new` self-heals for free on the next one. Writing `manual` here
    would charge a hand-edit in Sheets for what a re-roll fixes.
    """
    return bool(_PLACEHOLDER_RE.search(body or ""))


# What the summariser answers when it is handed a bare URL: it has no web access,
# so it politely asks for the text instead. Intake used to store that answer in
# «Вакансия», and the cover letter was then written from it — a letter to a live
# recruiter whose entire brief was "пришлите текст объявления". Intake no longer
# does this (it leaves the column empty), but rows written before the fix carry
# the sentence verbatim, so the refusal has to be recognised, not just emptiness.
#
# Anchored to the FIRST 40 characters, deliberately. A refusal opens with the
# phrase — both stored ones start at index 0, and the politest prefix a model
# reaches for ("К сожалению, ") is 13 — while a genuine vacancy that contains
# "не удалось извлечь" is describing the job ("если из источника не удалось
# извлечь структуру, инженер разбирается почему") and reaches it mid-sentence.
# 120 was the first guess and it swallowed exactly that sentence at index 72.
# Unlike the placeholder net above, the two costs here ARE comparable: a false
# positive costs a needless fetch, a false negative costs the recruiter a
# nonsense letter — so the window is set by where refusals actually start.
_REFUSAL_HEAD_CHARS = 40
_REFUSAL_RE = re.compile(
    r"не\s+(?:удалось|удаётся|удается|могу|получилось|смог|смогла)\s+"
    r"(?:извлеч|получ|прочит|открыт|найт)", re.IGNORECASE)

# The same failure, worded differently. Matching one family of phrasings was a
# guess made from two samples, and the run of 2026-07-29 produced two more that
# open nowhere near "не удалось" — leads 159 and 160 went out as `invited`
# carrying these as their brief:
#
#   "Похоже, ссылка ведёт на пост в LinkedIn, но содержимое вакансии из URL
#    недоступно. Пришлите текст объявления ..., и я кратко суммирую в JSON."
#   "Нет данных о вакансии в сообщении: предоставлена только ссылка без
#    описания роли, формата работы, условий и зарплаты."
#
# A model refuses in a new sentence every time, so listing openings does not
# converge. What every refusal DOES do, and a job advert never does, is talk
# about the message instead of the job: it says there is no vacancy here, or
# calls the link unreadable, or asks the reader to send the advert, or leaks the
# output format it was told to produce. Those four are the net.
#
# Window is 300 rather than 40: the first family opens with its phrase, this one
# reaches it mid-sentence ("недоступно" sits at index 78 above). The wider window
# is affordable precisely because these markers are refusal-shaped — a real advert
# does not contain "нет данных о вакансии" — where a bare "не удалось извлечь"
# can plausibly appear in prose about the job, which is why THAT one stays at 40.
_NO_VACANCY_HEAD_CHARS = 300
_NO_VACANCY_RE = re.compile(
    r"нет\s+(?:данных|информации|описания)\s+о?\s*ваканси|"
    r"(?:содержим|содержани)\w*\s+вакансии[^.]{0,40}недоступ|"
    r"(?:пришлите|предоставьте|отправьте|скиньте|укажите)\s+(?:полный\s+|сам\w*\s+)?"
    r"(?:текст|описание|содержание)\s+(?:объявлени|ваканси|поста)|"
    r"суммир\w*\s+в\s+JSON|"
    r"no\s+(?:job|vacancy)\s+(?:data|information|details)|"
    r"(?:please\s+)?(?:provide|paste|share)\s+the\s+(?:full\s+)?"
    r"(?:job\s+)?(?:description|posting|advert)",
    re.IGNORECASE)


def needs_vacancy_refetch(vacancy_context: str) -> bool:
    """True when the stored vacancy text is unusable and the link must be re-read.

    Three cases, all of which would otherwise become the basis of a cover letter:
    an empty column, and a stored model refusal in either of the two shapes above.
    Says nothing about whether the link CAN be re-read — that is the fetcher's
    business, not this predicate's.
    """
    text = (vacancy_context or "").strip()
    if not text:
        return True
    return bool(_REFUSAL_RE.search(text[:_REFUSAL_HEAD_CHARS])
                or _NO_VACANCY_RE.search(text[:_NO_VACANCY_HEAD_CHARS]))


def pause_after(result) -> bool:
    """Нужна ли анти-бан пауза после этого исхода отправки.

    Пауза покупает ровно одно: площадка не видит очередь сообщений, ушедших
    подряд с машинной равномерностью. Платить за неё (MIN..MAX секунд простоя
    на лид) имеет смысл там, где сообщение действительно ушло — обычная
    отправка и запрос на контакт С запиской, потому что записку читает живой
    человек и LinkedIn считает её текстом.

    Запрос на контакт БЕЗ записки (`invited_plain`) — это один клик «Connect» и
    ни строчки текста никому. Стоять после него минуту с лишним значит купить
    простой и ничего больше, поэтому здесь False.

    `rate_limited` пауза НУЖНА, и это единственный случай, где мы ждём после
    того, чего не отправили. С 2026-08-22 прогон не бросает площадку на первом
    лимите, а пробует следующего — по прямому решению владельца аккаунта. Без
    паузы эти попытки ушли бы очередью подряд, то есть ровно тем машинным
    паттерном, против которого пауза и заведена, и притом в момент, когда
    площадка уже показала спам-флаг. Ждать здесь нечего в смысле доставки, но
    есть что беречь — сам аккаунт.

    Остальные исходы (`manual`, ошибка) паузы не получают: ничего не
    отправлено, площадка молчит, ждать нечего.
    """
    return bool(result.ok or result.invited or result.rate_limited)
