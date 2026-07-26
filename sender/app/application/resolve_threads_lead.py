"""Turning a Threads lead into a sendable one.

The intake bot can only read a Threads post's ROOT text over plain HTTP, and it
cannot see the contact at all — that lives in the author's self-replies. So a
threads lead arrives deliberately incomplete, and this closes the gap right before
the message is generated: read the whole thread, find the real contact, and point
the lead at it.

Two invariants:
  * the lead is never lost — every failure path returns a usable lead;
  * the lead is never auto-skipped — no terminal status is written here at all.

The rules decide only what SHAPE decides
----------------------------------------
This is the first and only place `detect_contact` is pointed at Threads PROSE. The
intake bot runs it over the user's forwarded message — a URL — so `_HANDLE_RE`
taking the first `@handle` it sees has always been safe there. Over a whole
rendered thread it is not: "Ищем разработчика в @acmecorp", "Спасибо @kollega за
репост", "Стек: @nestjs и @supabase" each yield a confident-looking Telegram
contact pointing at a stranger. The upstream half of this feature makes it worse on
purpose — the DOM reader unwraps mention anchors so `@nick` arrives glued, which is
exactly the shape the rule takes.

Positional heuristics were tried and abandoned: whether an apply cue sat on the
same line, the previous line, or within N characters, each variant traded one
failure for its mirror image. The discrimination is not available in the text's
shape — a cue stem near a mention does not separate "here is where to write" from
"thanks for writing" or "do not write here", and "@kollega\\nотклики принимаем
только на сайте" is positionally identical to "Отклики:\\n@hr_acme". It is a
semantic question, so the rules stop asking it.

What the rules answer is the question they can:

  * an unambiguous shape — `t.me/…`, an email, a LinkedIn/hh/Wellfound URL — is a
    contact. Nobody writes one of those by accident. Auto-sent, as always.
  * a bare `@handle` is never selected. It is masked out and detection re-runs, so
    an unambiguous shape behind it still wins.
  * if nothing unambiguous remains, the MODEL is asked. It is the only component
    that can read whether a mention is the apply contact or a bystander; its answer
    goes through the five checks in `contact_llm` and carries REVIEW_MODEL, so it
    is held under AUTO_SEND and shown to a human in the default mode.

The cost is deliberate: "Для отклика в Telegram: @hr_acme" no longer auto-sends on
the rules alone. Under AUTO_SEND=false — the documented default — that is one
keypress, because the contact is printed before the send prompt.
"""
import re
from dataclasses import replace

from app.application.contact_llm import parse_contact_response
from app.domain.contact import detect_contact
from app.infrastructure.threads_thread import author_from_url

# Why a contact needs a human before it is sent. "" = it does not.
REVIEW_MODEL = "контакт предложен моделью, а не правилами — нужна проверка человеком"


def _is_bare_mention(contact) -> bool:
    """A Telegram hit that is an "@handle" rather than a t.me link."""
    return contact.platform == "telegram" and contact.target.startswith("@")


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

    `review` is why a human must look before it goes out, or "" when the contact
    was decided by shape alone.
    """
    contact = detect(text)

    # Step over every bare mention, unconditionally: an email or a t.me link
    # further down the post is a contact, "@kollega" is only a name. Terminates
    # because each pass strictly shrinks the text; the equality check also stops a
    # detector — an injectable seam — that returns a handle the text does not hold.
    while contact is not None and _is_bare_mention(contact):
        masked = _mask_handle(text, contact.target)
        if masked == text:
            break
        text = masked
        contact = detect(text)

    if contact is not None:
        return contact.platform, contact.target, ""

    if llm is not None:
        # The only component that can read a mention's ROLE. Its answer is vetted
        # by parse_contact_response — including check 5, which is what now keeps
        # the author's own Threads handle from becoming a Telegram target.
        try:
            contact = parse_contact_response(llm(text), text, author)
        except Exception:  # noqa: BLE001 — OpenAI being down is not a lost lead
            contact = None
        if contact is not None:
            return contact.platform, contact.target, REVIEW_MODEL

    # Nothing to apply to but the author — the DM fallback.
    return "threads", author, ""


def resolve_threads_lead(lead, repo, render, detect=detect_contact, llm=None):
    """A threads `lead` re-pointed at the real contact found inside its thread.

    `render(url) -> str` returns the author's own posts joined, or "" if the thread
    could not be read. `llm(thread_text) -> str` is the optional fallback detector
    (a raw model answer); it is consulted only when no unambiguous contact shape is
    in the thread, and its answer is vetted by `parse_contact_response` before it
    can become a recipient.

    Returns `(lead, review)`: the lead to send — rewritten when the thread was
    read, the original object otherwise — and why a human must look at the contact
    before it goes out, or "" when shape alone decided it. The caller needs that
    second value: an unattended run must not send a contact nobody has read (see
    `send_plan.hold_reason`).
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
