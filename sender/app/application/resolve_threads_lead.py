"""Turning a Threads lead into a sendable one.

The intake bot can only read a Threads post's ROOT text over plain HTTP, and it
cannot see the contact at all — that lives in the author's self-replies. So a
threads lead arrives deliberately incomplete, and this closes the gap right before
the message is generated: read the whole thread, find the real contact, and point
the lead at it.

Two invariants:
  * the lead is never lost — every failure path returns a usable lead;
  * the lead is never auto-skipped — no terminal status is written here at all.

Confidence, and why it is not the same as detection
---------------------------------------------------
This is the first and only place the rules are pointed at Threads PROSE. The
intake bot runs `detect_contact` over the user's forwarded message — a URL — so
`_HANDLE_RE` taking the first `@handle` it sees has always been safe there. Over a
whole rendered thread it is not: "Ищем разработчика в @acmecorp", "Спасибо
@kollega за репост", "Стек: @nestjs и @supabase" each yield a confident-looking
Telegram contact pointing at a stranger. The upstream half of this very feature
makes it worse on purpose — the DOM reader unwraps mention anchors so `@nick`
arrives glued, which is exactly the shape the rule takes.

So a detection carries a confidence, decided by SHAPE:

  * `t.me/…`, an email, a LinkedIn/hh/Wellfound URL — unambiguous. Nobody writes
    one of those by accident, so these send as they always have.
  * a bare `@handle` — ambiguous. Trusted only when an apply cue sits just before
    it on the same line ("Резюме в Telegram: @nick"). Otherwise the detection is
    kept, but flagged for review, which routes it exactly like a model-proposed
    contact: held under AUTO_SEND, surfaced loudly when a human is watching.

`contact.py:44-49` predicted this rule's shape and its home ("a contextual one
applied in the resolver, glue only where a telegram/тг cue sits just before it");
this extends the idea from gluing to confidence.
"""
import re
from dataclasses import replace

from app.application.contact_llm import parse_contact_response
from app.domain.contact import detect_contact
from app.infrastructure.threads_thread import author_from_url

# Why a contact needs a human before it is sent. "" = it does not.
REVIEW_MODEL = "контакт предложен моделью, а не правилами — нужна проверка человеком"
REVIEW_UNCUED = "@-упоминание без подсказки на отклик — нужна проверка человеком"

# An apply cue: either WHERE to write ("Telegram", "тг", "в личку") or WHAT to do
# ("для отклика", "резюме", "присылайте"). Stems, so morphology comes free —
# "отклик" covers "отклика/отклики/откликнуться", "пиш" covers "пишите/пиши".
# \b on both sides so "тг" cannot fire inside "отгрузка".
_CUE_RE = re.compile(
    r"\b(?:telegram|телеграм\w*|телег[ауи]|тг|tg|t\.me|dm|лс|личк\w*|директ\w*|"
    r"отклик\w*|пиш\w*|напиш\w*|резюме|cv|портфолио|связ\w*|контакт\w*|"
    r"присыл\w*|кидай\w*|скидыв\w*|анкет\w*)\b",
    re.IGNORECASE)

# Characters allowed between the end of the cue and the "@". Chosen against the
# real texts rather than by feel: genuine contact lines put the cue right next to
# the handle — "Telegram: @nick" is a gap of 2, "Резюме присылайте сюда: @nick" is
# 7 — while the false positives this rule exists to catch have their cue at the
# far end of a sentence: "Пишите нам, ищем разработчика, стек @nestjs" is a gap of
# 29. 20 sits between the two with room on either side.
_CUE_WINDOW = 20

# How many uncued mentions to step over while looking for something unambiguous.
# Bounded because each step re-runs the detector over the whole thread.
_MAX_MENTION_SKIPS = 5


def mention_is_cued(text: str, handle: str) -> bool:
    """True when an apply cue sits just before `handle` on its own line.

    Line-scoped on purpose: a cue two sentences up, on another line, says nothing
    about this mention.
    """
    nick = (handle or "").lstrip("@").strip()
    if not nick:
        return False
    at_re = re.compile(r"@\s*" + re.escape(nick) + r"\b", re.IGNORECASE)
    for line in (text or "").splitlines():
        for m in at_re.finditer(line):
            ends = [c.end() for c in _CUE_RE.finditer(line[:m.start()])]
            if ends and m.start() - max(ends) <= _CUE_WINDOW:
                return True
    return False


def _same_handle(target: str, author: str) -> bool:
    return (target or "").strip().lstrip("@").lower() == (author or "").lstrip("@").lower()


def _mask_handle(text: str, handle: str) -> str:
    """`text` with "@nick" written as plain "nick", so the rules stop seeing it.

    Anchored like `_HANDLE_RE` itself (start-or-whitespace before the at-sign), so
    it cannot reach inside an address such as "hr@nick.com".
    """
    nick = (handle or "").lstrip("@").strip()
    if not nick:
        return text
    return re.sub(rf"(^|\s)@\s*{re.escape(nick)}\b", lambda m: m.group(1) + nick,
                  text, flags=re.IGNORECASE | re.MULTILINE)


def _route(text, author, detect, llm):
    """Where this thread should be sent, as (platform, target, review).

    `review` is why a human must look before it goes out, or "" when the detection
    is unambiguous.
    """
    contact = detect(text)
    scan = text
    uncued = None

    # Walk past bare @mentions that nothing marks as a contact, masking each one
    # and looking again, so an email or a t.me link further down the post still
    # wins over "Спасибо @kollega за репост". The first uncued mention is kept as
    # the fallback: the detection is not thrown away, only demoted.
    for _ in range(_MAX_MENTION_SKIPS):
        if contact is None or contact.platform != "telegram" \
                or not contact.target.startswith("@"):
            break                       # nothing, or an unambiguous shape
        if author and _same_handle(contact.target, author):
            # The author's own Threads handle is NOT a Telegram username. When they
            # write "пишите мне @lnkrnchk" in their own post, detect_contact reads
            # it as Telegram and we would DM whoever holds that name there — a
            # different person. The intake copy of detect_contact guards this by
            # exempting the author parsed out of the URL; the sender copy cannot,
            # because its input is rendered prose with no URL in it. So the guard
            # lives here, where the author IS known. Masked rather than dropped:
            # "Я @lnkrnchk, ищем разработчика. Резюме на hr@acme.io" carries a
            # perfectly good deterministic email behind it.
            pass
        elif mention_is_cued(scan, contact.target):
            break                       # a cue marks this one as the contact
        elif uncued is None:
            uncued = contact
        scan = _mask_handle(scan, contact.target)
        contact = detect(scan)

    review = ""
    if contact is None:
        if uncued is not None:
            contact, review = uncued, REVIEW_UNCUED
        elif llm is not None:
            # Rules first, model second: this only ever runs on text the
            # deterministic rules could not read (the live "Telegram: @
            # skyluckwalker" — a space the author typed, which no regex takes).
            try:
                contact = parse_contact_response(llm(text), text, author)
            except Exception:  # noqa: BLE001 — OpenAI being down is not a lost lead
                contact = None
            if contact is not None:
                review = REVIEW_MODEL
    elif contact.platform == "telegram" and contact.target.startswith("@") \
            and not mention_is_cued(scan, contact.target):
        # Only reachable by running out of skips in a post full of mentions.
        contact, review = (uncued or contact), REVIEW_UNCUED

    if contact is None:
        # Nothing to apply to but the author — the DM fallback.
        return "threads", author, ""
    return contact.platform, contact.target, review


def resolve_threads_lead(lead, repo, render, detect=detect_contact, llm=None):
    """A threads `lead` re-pointed at the real contact found inside its thread.

    `render(url) -> str` returns the author's own posts joined, or "" if the thread
    could not be read. `llm(thread_text) -> str` is the optional fallback detector
    (a raw model answer); it is consulted ONLY when the rules found nothing, and
    its answer is vetted by `parse_contact_response` before it can become a
    recipient.

    Returns `(lead, review)`: the lead to send — rewritten when the thread was
    read, the original object otherwise — and why a human must look at the contact
    before it goes out, or "" when the detection is unambiguous. The caller needs
    that second value: an unattended run must not send a contact nobody has read
    (see `send_plan.hold_reason`).
    """
    if lead.platform != "threads":
        return lead, ""

    try:
        text = render(lead.target)
    except Exception:  # noqa: BLE001 — an unreadable thread is not a lost lead
        text = ""
    if not text:
        # Keep whatever the intake stored. Status stays `new` so the next run,
        # possibly with a working browser, tries again.
        return lead, ""

    # A partial render (hydration dropped a reply) must never shrink the vacancy.
    vacancy = text if len(text) >= len(lead.vacancy_context or "") else lead.vacancy_context

    try:
        author = author_from_url(lead.target)
    except Exception:  # noqa: BLE001
        author = ""
    try:
        platform, target, review = _route(text, author, detect, llm)
    except Exception:  # noqa: BLE001 — `detect` is an injectable seam and this
        # function's contract is that it never raises: a detector that throws must
        # cost the thread's contact, not the lead itself.
        platform, target, review = "threads", author, ""

    if platform == "threads":
        target = target or lead.target
        note = f"контакта в треде нет, DM автору: {lead.target}"
    elif review:
        note = f"{review}: {platform} → {target}; тред: {lead.target}"
        print(f"   ⚠️  {review}: {platform} → {target}")
    else:
        note = f"контакт из треда Threads: {lead.target}"

    # The caller owns a non-empty target: update_resolved blanks Источник while
    # setting Платформа, and skip_reason gates only on the platform — so a blank
    # target means the next run opens a Telegram channel and sends to "".
    if not target:
        return lead, ""

    try:
        repo.update_resolved(lead, platform, target, vacancy, note=note)
    except Exception as exc:  # noqa: BLE001 — the sheet is a record, the send is the point
        # Not silent. The write is atomic within itself, but not across the pair
        # (write, then send): if it failed we still send via the resolved route,
        # so the message reaches the right person while the row keeps the old
        # platform/target and is later stamped `sent`. That is a wrong record,
        # not a wrong recipient, and it is recoverable by re-resolving — but the
        # human has to know it happened.
        print(f"⚠️  #{lead.lead_id}: строку в таблице обновить не удалось "
              f"({type(exc).__name__}). Отправляю по найденному контакту, "
              f"но в таблице останется старая платформа.")

    return replace(lead, platform=platform, target=target, vacancy_context=vacancy), review
