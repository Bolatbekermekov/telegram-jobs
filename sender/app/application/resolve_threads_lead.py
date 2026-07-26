"""Turning a Threads lead into a sendable one.

The intake bot can only read a Threads post's ROOT text over plain HTTP, and it
cannot see the contact at all — that lives in the author's self-replies. So a
threads lead arrives deliberately incomplete, and this closes the gap right before
the message is generated: read the whole thread, find the real contact, and point
the lead at it.

Two invariants:
  * the lead is never lost — every failure path returns a usable lead;
  * the lead is never auto-skipped — no terminal status is written here at all.
"""
from dataclasses import replace

from app.application.contact_llm import parse_contact_response
from app.domain.contact import detect_contact
from app.infrastructure.threads_thread import author_from_url


def resolve_threads_lead(lead, repo, render, detect=detect_contact, llm=None):
    """A threads `lead` re-pointed at the real contact found inside its thread.

    `render(url) -> str` returns the author's own posts joined, or "" if the thread
    could not be read. `llm(thread_text) -> str` is the optional fallback detector
    (a raw model answer); it is consulted ONLY when the rules found nothing, and
    its answer is vetted by `parse_contact_response` before it can become a
    recipient.

    Returns `(lead, contact_from_model)`: the lead to send — rewritten when the
    thread was read, the original object otherwise — and whether its contact came
    from the model rather than from the rules. The caller needs that second value:
    an unattended run must not send a contact no human has read, because the
    vetting proves the target was WRITTEN in the thread, not that it is the
    address to apply to (see `send_plan.hold_reason`).
    """
    if lead.platform != "threads":
        return lead, False

    try:
        text = render(lead.target)
    except Exception:  # noqa: BLE001 — an unreadable thread is not a lost lead
        text = ""
    if not text:
        # Keep whatever the intake stored. Status stays `new` so the next run,
        # possibly with a working browser, tries again.
        return lead, False

    # A partial render (hydration dropped a reply) must never shrink the vacancy.
    vacancy = text if len(text) >= len(lead.vacancy_context or "") else lead.vacancy_context

    author = author_from_url(lead.target)
    contact = detect(text)
    # The author's own Threads handle is NOT a Telegram username. When they write
    # "пишите мне @lnkrnchk" in their own post, detect_contact reads it as Telegram
    # and we would DM whoever holds that name there — a different person. The
    # intake copy of detect_contact guards this by exempting the author parsed out
    # of the URL; the sender copy cannot, because its input is rendered prose with
    # no URL in it. So the guard lives here, where the author IS known.
    if contact is not None and contact.platform == "telegram" and author:
        if contact.target.strip().lstrip("@").lower() == author.lstrip("@").lower():
            contact = None

    by_model = False
    if contact is None and llm is not None:
        # Rules first, model second: this only ever runs on text the deterministic
        # rules could not read (the live "Telegram: @ skyluckwalker", a space the
        # author typed and no regex can safely take).
        try:
            contact = parse_contact_response(llm(text), text, author)
        except Exception:  # noqa: BLE001 — OpenAI being down is not a lost lead
            contact = None
        by_model = contact is not None

    if contact is not None:
        platform, target = contact.platform, contact.target
        if by_model:
            # Visible to the human: this passed validation but it is still a guess,
            # and `make run` asks before sending.
            note = f"контакт определён моделью из треда Threads: {lead.target}"
            print(f"   контакт определён моделью (проверь перед отправкой): "
                  f"{platform} → {target}")
        else:
            note = f"контакт из треда Threads: {lead.target}"
    else:
        # Nothing to apply to but the author — the DM fallback. This branch
        # overwrites Источник with the handle, so the note below is the only
        # remaining pointer back to the post.
        platform = "threads"
        target = author or lead.target
        note = f"контакта в треде нет, DM автору: {lead.target}"

    # The caller owns a non-empty target: update_resolved blanks Источник while
    # setting Платформа, and skip_reason gates only on the platform — so a blank
    # target means the next run opens a Telegram channel and sends to "".
    if not target:
        return lead, False

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

    return replace(lead, platform=platform, target=target, vacancy_context=vacancy), by_model
