"""Resolving a threads lead into a sendable one.

Two invariants are load-bearing here and are asserted directly: a lead is never
lost, and it is never auto-skipped. The worst acceptable outcome is "stays as it
was, with a note".

On the two fixtures below: `_FULL` is the live post that motivated the model
fallback — its author typed "Telegram: @ skyluckwalker", with a space, and no
regex takes that (contact.py records why a blanket `@\\s+` rule was tried and
reverted). So `_FULL` exercises the model path and `_GLUED` exercises the rule
path; using `_FULL` for the rule path would assert a detection that cannot
happen.
"""
from app.application.resolve_threads_lead import (
    REVIEW_AMBIGUOUS, REVIEW_MODEL, REVIEW_UNCUED, resolve_threads_lead,
)
from app.domain.lead import STATUS_NEW, Lead

_URL = "https://www.threads.com/@lnkrnchk/post/DbL4LxBl6v9"

_FULL = ("Ищу Full Stack Developer (Lovable / Claude Code / AI-first).\n\n"
         "Что важно: опыт с Lovable, Claude Code, Cursor, Supabase.\n\n"
         "Для отклика присылайте портфолио в Telegram: @ skyluckwalker")

_GLUED = _FULL.replace("@ skyluckwalker", "@skyluckwalker")

_FOUND = '{"platform": "telegram", "target": "@skyluckwalker"}'


def _lead(**kw):
    base = dict(row=5, lead_id="7", platform="threads", target=_URL,
                vacancy_context="Ищу Full Stack Developer (обрезано)",
                raw_text=_URL, status=STATUS_NEW)
    base.update(kw)
    return Lead(**base)


class FakeRepo:
    def __init__(self):
        self.resolved = []
        self.statuses = []

    def update_resolved(self, lead, platform, target, vacancy_context, note=""):
        self.resolved.append((lead.row, platform, target, vacancy_context, note))

    def mark_status(self, lead, status, note=""):
        self.statuses.append((lead.row, status, note))


# --- the rule path --------------------------------------------------------

def test_contact_found_in_the_thread_switches_the_platform():
    repo = FakeRepo()
    out, _ = resolve_threads_lead(_lead(), repo, render=lambda url: _GLUED)
    assert out.platform == "telegram"
    assert out.target == "@skyluckwalker"
    assert "Что важно" in out.vacancy_context


def test_contact_found_is_persisted_once():
    repo = FakeRepo()
    resolve_threads_lead(_lead(), repo, render=lambda url: _GLUED)
    assert len(repo.resolved) == 1
    row, platform, target, text, note = repo.resolved[0]
    assert (row, platform, target) == (5, "telegram", "@skyluckwalker")
    assert "Что важно" in text
    assert _URL in note, "в заметке должна остаться ссылка на исходный тред"


def test_no_contact_in_the_thread_keeps_threads_and_targets_the_author():
    """The DM fallback: platform stays threads, target becomes the author."""
    repo = FakeRepo()
    text = "Ищем разработчика. Формат: удалённо, full-time. Пишите в комментарии."
    out, _ = resolve_threads_lead(_lead(), repo, render=lambda url: text)
    assert out.platform == "threads"
    assert out.target == "@lnkrnchk"
    assert out.vacancy_context == text
    assert repo.resolved[0][1] == "threads"


def test_the_dm_fallback_keeps_the_thread_url_in_the_note():
    """Load-bearing, not decorative: this branch overwrites Источник with the
    author's handle, so the note becomes the only pointer back to the post."""
    repo = FakeRepo()
    resolve_threads_lead(_lead(), repo,
                         render=lambda url: "Ищем разработчика, пишите в комментарии.")
    assert _URL in repo.resolved[0][4]


def test_render_failure_leaves_the_lead_untouched():
    """No render, no rewrite: the 480 chars from intake are still better than
    nothing, and the lead must stay `new` for the next run."""
    repo = FakeRepo()
    original = _lead()
    out, _ = resolve_threads_lead(original, repo, render=lambda url: "")
    assert out is original
    assert repo.resolved == []


def test_render_failure_is_never_a_skip():
    repo = FakeRepo()
    resolve_threads_lead(_lead(), repo, render=lambda url: "")
    assert repo.statuses == [], "резолв не имеет права ставить терминальный статус"


def test_render_raising_is_swallowed():
    repo = FakeRepo()

    def boom(url):
        raise RuntimeError("browser died")

    out, _ = resolve_threads_lead(_lead(), repo, render=boom)
    assert out.platform == "threads" and repo.resolved == []


def test_a_persist_failure_still_returns_the_resolved_lead_in_memory():
    """Sheets being down must not cost us the send: the rewrite is a convenience,
    the in-memory lead is what the run uses."""
    class BrokenRepo(FakeRepo):
        def update_resolved(self, *a, **kw):
            raise RuntimeError("sheets 503")

    out, _ = resolve_threads_lead(_lead(), BrokenRepo(), render=lambda url: _GLUED)
    assert out.platform == "telegram" and out.target == "@skyluckwalker"


def test_a_persist_failure_is_reported_to_the_human(capsys):
    """Silently sending on a row that still says `threads` is a wrong record the
    human has to know about — it is only recoverable if they see it."""
    class BrokenRepo(FakeRepo):
        def update_resolved(self, *a, **kw):
            raise RuntimeError("sheets 503")

    resolve_threads_lead(_lead(), BrokenRepo(), render=lambda url: _GLUED)
    out = capsys.readouterr().out
    assert "#7" in out and "таблиц" in out


def test_the_authors_own_handle_is_not_treated_as_a_telegram_contact():
    """Found while implementing Task 4. "@lnkrnchk" written by @lnkrnchk in their
    own post is their THREADS name, not a Telegram username — DMing it would reach
    a different person. The intake copy of detect_contact exempts the author from
    the URL; the sender copy gets rendered prose with no URL, so the guard is here."""
    repo = FakeRepo()
    text = "Ищем разработчика. Пишите мне @lnkrnchk, отвечаю быстро."
    out, _ = resolve_threads_lead(_lead(), repo, render=lambda url: text)
    assert out.platform == "threads"
    assert out.target == "@lnkrnchk"          # the DM fallback, not a Telegram DM


def test_a_different_handle_in_the_authors_post_still_wins():
    repo = FakeRepo()
    text = "Ищем разработчика. Резюме в Telegram: @hiring_bot_hr"
    out, _ = resolve_threads_lead(_lead(), repo, render=lambda url: text)
    assert out.platform == "telegram"
    assert out.target == "@hiring_bot_hr"


def test_non_threads_leads_are_returned_as_is():
    repo = FakeRepo()
    lead = _lead(platform="hh", target="https://hh.ru/vacancy/1")
    called = []
    out, _ = resolve_threads_lead(lead, repo, render=lambda url: called.append(url) or "")
    assert out is lead and called == []


def test_shorter_resolved_text_does_not_replace_a_longer_stored_one():
    """A partial render (hydration lost a reply) must not shrink the vacancy."""
    repo = FakeRepo()
    lead = _lead(vacancy_context="a" * 900)
    out, _ = resolve_threads_lead(lead, repo, render=lambda url: "короткий огрызок")
    assert out.vacancy_context == "a" * 900


def test_an_empty_target_leaves_the_row_alone():
    """update_resolved blanks Источник while setting Платформа, and skip_reason
    gates only on the platform — a blank target means the NEXT run opens a channel
    and sends to "". Nothing to point at means: do not rewrite the row."""
    repo = FakeRepo()
    lead = _lead(target="")
    out, _ = resolve_threads_lead(lead, repo, render=lambda url: "Ищем разработчика.")
    assert out is lead
    assert repo.resolved == [] and repo.statuses == []


# --- the model fallback ---------------------------------------------------

def test_the_model_is_not_asked_when_the_rules_found_a_contact():
    """Rules decide first. Every pre-existing lead keeps its deterministic path."""
    repo = FakeRepo()
    asked = []

    out, _ = resolve_threads_lead(_lead(), repo, render=lambda url: _GLUED,
                               llm=lambda text: asked.append(text) or _FOUND)
    assert asked == []
    assert out.target == "@skyluckwalker"


def test_the_model_recovers_a_contact_the_rules_cannot_see():
    """The live case: "Telegram: @ skyluckwalker" — a space the author typed."""
    repo = FakeRepo()
    out, _ = resolve_threads_lead(_lead(), repo, render=lambda url: _FULL,
                               llm=lambda text: _FOUND)
    assert (out.platform, out.target) == ("telegram", "@skyluckwalker")


def test_the_model_is_given_the_thread_text():
    repo = FakeRepo()
    asked = []
    resolve_threads_lead(_lead(), repo, render=lambda url: _FULL,
                         llm=lambda text: asked.append(text) or _FOUND)
    assert asked == [_FULL]


def test_a_model_found_contact_is_marked_as_such_in_the_note():
    repo = FakeRepo()
    resolve_threads_lead(_lead(), repo, render=lambda url: _FULL,
                         llm=lambda text: _FOUND)
    note = repo.resolved[0][4]
    assert "модел" in note.lower() and _URL in note


def test_a_model_found_contact_is_announced_to_the_human(capsys):
    """It is a guess that passed validation, not a rule — the human approving the
    send in `make run` is told so before they press [s]."""
    repo = FakeRepo()
    resolve_threads_lead(_lead(), repo, render=lambda url: _FULL,
                         llm=lambda text: _FOUND)
    assert "модел" in capsys.readouterr().out.lower()


def test_no_model_means_the_old_behaviour():
    repo = FakeRepo()
    out, _ = resolve_threads_lead(_lead(), repo, render=lambda url: _FULL)
    assert (out.platform, out.target) == ("threads", "@lnkrnchk")


def test_a_model_that_raises_falls_back_to_the_dm():
    repo = FakeRepo()

    def boom(text):
        raise RuntimeError("openai 429")

    out, _ = resolve_threads_lead(_lead(), repo, render=lambda url: _FULL, llm=boom)
    assert (out.platform, out.target) == ("threads", "@lnkrnchk")


def test_a_model_answer_that_fails_validation_falls_back_to_the_dm():
    """An invented handle never becomes a recipient."""
    repo = FakeRepo()
    out, from_model = resolve_threads_lead(
        _lead(), repo, render=lambda url: _FULL,
        llm=lambda text: '{"platform": "telegram", "target": "@totally_made_up"}')
    assert (out.platform, out.target) == ("threads", "@lnkrnchk")
    assert repo.resolved[0][1] == "threads"
    assert from_model == "", "отброшенный ответ модели — это не контакт, требующий проверки"


def test_the_model_cannot_hand_back_the_authors_handle_as_telegram():
    repo = FakeRepo()
    text = "Ищем разработчика. Пишите мне @ lnkrnchk, отвечаю быстро."
    out, _ = resolve_threads_lead(
        _lead(), repo, render=lambda url: text,
        llm=lambda t: '{"platform": "telegram", "target": "@lnkrnchk"}')
    assert (out.platform, out.target) == ("threads", "@lnkrnchk")


def test_the_model_still_runs_after_the_rules_hit_only_the_author():
    """The rule guard nulls the author's handle; the model then gets its chance
    at the contact the rules could not glue."""
    repo = FakeRepo()
    text = ("Ищем разработчика. Я @lnkrnchk, автор поста.\n"
            "Отклики в телеграм: @ hiring_acme")
    out, _ = resolve_threads_lead(
        _lead(), repo, render=lambda url: text,
        llm=lambda t: '{"platform": "telegram", "target": "@hiring_acme"}')
    assert (out.platform, out.target) == ("telegram", "@hiring_acme")


# --- which contacts need a human ------------------------------------------
# The send loop has to tell these apart without re-parsing the note: an unattended
# run must not send a contact nobody has read (send_plan.hold_reason).

def test_a_cued_rules_contact_needs_no_review():
    out, review = resolve_threads_lead(_lead(), FakeRepo(),
                                       render=lambda url: _GLUED)
    assert out.platform == "telegram" and review == ""


def test_a_model_contact_needs_review():
    out, review = resolve_threads_lead(_lead(), FakeRepo(),
                                       render=lambda url: _FULL,
                                       llm=lambda text: _FOUND)
    assert out.platform == "telegram" and review == REVIEW_MODEL


def test_the_dm_fallback_needs_no_review():
    out, review = resolve_threads_lead(
        _lead(), FakeRepo(),
        render=lambda url: "Ищем разработчика, пишите в комментарии.")
    assert out.platform == "threads" and review == ""


def test_an_unresolved_lead_needs_no_review():
    """Both untouched paths: an unreadable thread and a non-threads lead."""
    repo = FakeRepo()
    assert resolve_threads_lead(_lead(), repo, render=lambda url: "")[1] == ""
    assert resolve_threads_lead(_lead(platform="hh"), repo,
                                render=lambda url: _FULL)[1] == ""


# --- confidence: a bare @mention is not automatically a contact ------------
# detect_contact takes the FIRST @handle anywhere in the text. Over a URL (all the
# intake ever feeds it) that is safe; over a whole rendered thread it points at
# strangers. These are the exact texts that motivated the rule.

def test_a_company_mention_in_prose_is_not_auto_sent():
    repo = FakeRepo()
    text = "Ищем разработчика в @acmecorp. Пишите в комментарии."
    out, review = resolve_threads_lead(_lead(), repo, render=lambda url: text)
    assert (out.platform, out.target) == ("telegram", "@acmecorp")
    assert review == REVIEW_UNCUED, "без подсказки такой контакт нельзя слать молча"
    assert REVIEW_UNCUED in repo.resolved[0][4] and _URL in repo.resolved[0][4]


def test_a_thanks_mention_loses_to_the_real_email_further_down():
    """The mention is stepped over, not just flagged — the email is the contact."""
    repo = FakeRepo()
    text = "Спасибо @kollega за репост! Ищем разработчика. Резюме на hr@acme.io"
    out, review = resolve_threads_lead(_lead(), repo, render=lambda url: text)
    assert (out.platform, out.target) == ("email", "hr@acme.io")
    assert review == ""


def test_a_stack_mention_is_not_a_contact():
    repo = FakeRepo()
    text = "Стек: @nestjs и @supabase. Отклики в комментарии."
    out, review = resolve_threads_lead(_lead(), repo, render=lambda url: text)
    assert out.target == "@nestjs" and review == REVIEW_UNCUED


def test_a_cued_mention_still_auto_sends():
    """The cue is what separates a contact from a mention, and genuine contact
    lines carry one — usually two."""
    repo = FakeRepo()
    text = "Ищем разработчика. Для отклика пишите в Telegram: @hiring_acme"
    out, review = resolve_threads_lead(_lead(), repo, render=lambda url: text)
    assert (out.platform, out.target) == ("telegram", "@hiring_acme")
    assert review == ""


def test_an_uncued_tme_link_still_auto_sends():
    """Shape decides: nobody writes a t.me link by accident."""
    repo = FakeRepo()
    text = "Стек @nestjs. Наш канал https://t.me/acmejobs"
    out, review = resolve_threads_lead(_lead(), repo, render=lambda url: text)
    assert (out.platform, out.target) == ("telegram", "https://t.me/acmejobs")
    assert review == ""


def test_an_uncued_email_still_auto_sends():
    repo = FakeRepo()
    text = "Ищем разработчика в Acme. hr@acme.io"
    out, review = resolve_threads_lead(_lead(), repo, render=lambda url: text)
    assert (out.platform, out.target) == ("email", "hr@acme.io")
    assert review == ""


def test_an_uncued_hh_link_still_auto_sends():
    repo = FakeRepo()
    text = "Ищем разработчика. https://hh.ru/vacancy/135297431"
    out, review = resolve_threads_lead(_lead(), repo, render=lambda url: text)
    assert out.platform == "hh" and review == ""


def test_a_cue_on_another_line_does_not_vouch_for_a_mention():
    """Line-scoped: "пишите" two lines up says nothing about this mention."""
    repo = FakeRepo()
    text = "Пишите нам!\nМы работаем со стеком @supabase каждый день."
    _, review = resolve_threads_lead(_lead(), repo, render=lambda url: text)
    assert review == REVIEW_UNCUED


def test_a_far_away_cue_on_the_same_line_does_not_vouch_either():
    repo = FakeRepo()
    text = "Пишите нам, ищем разработчика, стек @nestjs"
    _, review = resolve_threads_lead(_lead(), repo, render=lambda url: text)
    assert review == REVIEW_UNCUED


# --- the author guard keeps the rest of the detection ----------------------

def test_masking_the_author_keeps_a_good_email_behind_it():
    """Dropping the whole detection lost this email to the DM fallback."""
    repo = FakeRepo()
    text = "Я @lnkrnchk, ищем разработчика. Резюме на hr@acme.io"
    out, review = resolve_threads_lead(_lead(), repo, render=lambda url: text)
    assert (out.platform, out.target) == ("email", "hr@acme.io")
    assert review == ""


def test_the_author_alone_still_falls_back_to_the_dm():
    repo = FakeRepo()
    text = "Ищем разработчика. Пишите мне @lnkrnchk, отвечаю быстро."
    out, review = resolve_threads_lead(_lead(), repo, render=lambda url: text)
    assert (out.platform, out.target) == ("threads", "@lnkrnchk")
    assert review == ""


# --- cues across lines ----------------------------------------------------
# threads_post.post_body joins every leaf span with "\n", so a self-reply whose
# whole content is the contact lands on its own line NECESSARILY. Measured on
# Task 5's captured spans: 3 of 3 contact spans are own-line, 0 of 3 put the cue
# on the handle's own line. A line-scoped rule parked all of these.

def test_a_cue_ending_the_previous_line_vouches():
    repo = FakeRepo()
    out, review = resolve_threads_lead(_lead(), repo,
                                       render=lambda url: "Отклики:\n@hiring_acme")
    assert (out.platform, out.target) == ("telegram", "@hiring_acme")
    assert review == ""


def test_a_cue_two_lines_up_does_not_vouch_but_the_line_above_does():
    repo = FakeRepo()
    text = "Ищем разработчика.\nРезюме в телеграм:\n@hiring_acme"
    _, review = resolve_threads_lead(_lead(), repo, render=lambda url: text)
    assert review == ""


def test_a_blank_line_between_the_cue_and_the_handle_is_stepped_over():
    repo = FakeRepo()
    text = "Что важно: React, Node\n\nКонтакты:\n@hiring_acme"
    out, review = resolve_threads_lead(_lead(), repo, render=lambda url: text)
    assert (out.platform, out.target) == ("telegram", "@hiring_acme")
    assert review == ""


def test_the_captured_dm_me_span_shape_auto_sends():
    """Verbatim from test_threads_post: post_body(["1 дн.","DM me:","@acme_hr","1"])."""
    repo = FakeRepo()
    out, review = resolve_threads_lead(_lead(), repo,
                                       render=lambda url: "DM me:\n@acme_hr")
    assert (out.platform, out.target) == ("telegram", "@acme_hr")
    assert review == ""


def test_a_cue_opening_the_next_line_vouches():
    """The other captured shape: post_body(...) == "@acme_hr\\nпишите в личку"."""
    repo = FakeRepo()
    out, review = resolve_threads_lead(_lead(), repo,
                                       render=lambda url: "@acme_hr\nпишите в личку")
    assert (out.platform, out.target) == ("telegram", "@acme_hr")
    assert review == ""


def test_a_neighbouring_cue_does_not_vouch_when_the_handle_shares_its_line():
    """The gate on the cross-line rule. Without it "Стек: @nestjs\\nОтклики в
    комментарии" would go out to a framework's account."""
    repo = FakeRepo()
    text = "Стек: @nestjs\nОтклики в комментарии."
    out, review = resolve_threads_lead(_lead(), repo, render=lambda url: text)
    assert out.target == "@nestjs" and review == REVIEW_UNCUED


def test_a_lone_mention_with_no_cue_on_either_side_is_still_held():
    repo = FakeRepo()
    text = "@nestjs\n\nИщем разработчика на этом стеке"
    _, review = resolve_threads_lead(_lead(), repo, render=lambda url: text)
    assert review == REVIEW_UNCUED


# --- a handle that is really a domain --------------------------------------

def test_a_handle_glued_to_a_tld_is_not_a_telegram_contact():
    """"Резюме на hr @acmecorp.com": _HANDLE_RE stops at the dot and the email rule
    never fires across the space, so the cue would have certified "@acmecorp"."""
    repo = FakeRepo()
    out, review = resolve_threads_lead(_lead(), repo,
                                       render=lambda url: "Резюме на hr @acmecorp.com")
    assert out.target != "@acmecorp"
    assert out.platform == "threads"          # stepped over, nothing else found


def test_a_short_domain_tail_is_caught_too():
    repo = FakeRepo()
    out, _ = resolve_threads_lead(_lead(), repo,
                                  render=lambda url: "CV на jobs @acme.io")
    assert out.target != "@acme"


def test_stepping_over_a_domain_tail_lets_the_model_recover_the_address():
    """Why it is stepped over rather than held: the address is right there, and the
    model reads the spaced form the rules cannot."""
    repo = FakeRepo()
    out, review = resolve_threads_lead(
        _lead(), repo, render=lambda url: "Резюме на hr @acmecorp.com",
        llm=lambda t: '{"platform": "email", "target": "hr@acmecorp.com"}')
    assert (out.platform, out.target) == ("email", "hr@acmecorp.com")
    assert review == REVIEW_MODEL


# --- two plausible contacts: decline to pick -------------------------------

def test_a_cued_mention_competing_with_an_email_is_held():
    """No text rule separates "the person who reviewed my CV" from "the person to
    send it to", so this declines to guess instead of guessing."""
    repo = FakeRepo()
    text = "Резюме смотрел @kollega, он рекомендовал; hr@acme.io"
    out, review = resolve_threads_lead(_lead(), repo, render=lambda url: text)
    assert out.target == "@kollega"
    assert review == REVIEW_AMBIGUOUS


def test_a_cued_mention_with_nothing_competing_still_auto_sends():
    """The narrow case stays automatic — that is the point of the hold being narrow."""
    repo = FakeRepo()
    text = "Ищем разработчика. Для отклика пишите в Telegram: @hiring_acme"
    _, review = resolve_threads_lead(_lead(), repo, render=lambda url: text)
    assert review == ""


def test_another_bare_mention_is_not_competition():
    """More ambiguity of the same kind is not an unambiguous alternative."""
    repo = FakeRepo()
    text = "Пишите нам: @hr_acme. Стек @nestjs"
    out, review = resolve_threads_lead(_lead(), repo, render=lambda url: text)
    assert (out.target, review) == ("@hr_acme", "")


def test_known_limit_the_ambiguity_hold_is_one_directional():
    """DOCUMENTS A LIMIT. The hold fires when a cued MENTION is selected and
    something unambiguous competes. The mirror image does not: detect_contact
    ranks t.me above bare handles, so here the link is selected and the cued
    mention never gets a say — no hold, and the outreach goes to the channel.

    Left as-is deliberately. The harm class differs: the ambiguity hold exists to
    stop a message reaching a BYSTANDER ("@kollega, who reviewed my CV"), whereas
    both candidates here are contacts the author published for being contacted
    through. Sending to the author's email or channel instead of their preferred
    Telegram handle is a worse guess, not a wrong recipient.
    """
    repo = FakeRepo()
    text = "Пишите @hr_acme\nили в канал https://t.me/acmejobs"
    out, review = resolve_threads_lead(_lead(), repo, render=lambda url: text)
    assert (out.target, review) == ("https://t.me/acmejobs", "")


def test_known_limit_a_cued_brand_mention_is_still_auto_sent():
    """DOCUMENTS A LIMIT, does not endorse it. The cue rule tests whether an apply
    word sits next to the handle — not whether the handle is a Telegram account.
    "Откликнуться можно у @acmecorp в шапке профиля" means "look at their Threads
    profile", but it reads as cued, so it goes out as a Telegram DM to whoever owns
    that name there. Threads and Telegram share the `@nick` shape and namespace, so
    no text rule closes this; it needs the handle checked against Telegram itself.
    If a later change starts flagging this, that is an improvement — update the test.
    """
    repo = FakeRepo()
    text = "Откликнуться можно у @acmecorp в шапке профиля"
    out, review = resolve_threads_lead(_lead(), repo, render=lambda url: text)
    assert (out.platform, out.target) == ("telegram", "@acmecorp")
    assert review == ""


def test_masking_does_not_reach_inside_an_address():
    """"@nick" is masked; "hr@nick.com" is left alone."""
    from app.application.resolve_threads_lead import _mask_handle
    assert _mask_handle("пишите @lnkrnchk или hr@lnkrnchk.com", "@lnkrnchk") == \
        "пишите lnkrnchk или hr@lnkrnchk.com"
