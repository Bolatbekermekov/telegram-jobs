"""Resolving a threads lead into a sendable one.

Two invariants are load-bearing here and are asserted directly: a lead is never
lost, and it is never auto-skipped. The worst acceptable outcome is "stays as it
was, with a note".

The third invariant, and the one this file spends most of its length on: **a bare
`@handle` from thread prose is never the recipient the rules choose.** Only shapes
nobody writes by accident — an email, a `t.me/…` link, a platform URL — are
contacts to the rules. Mentions are masked out and detection re-runs; if nothing
unambiguous is left, the model decides, and its answer is held for a human.

On the fixtures: `_UNAMBIGUOUS` drives the rules path, `_FULL` (the live post,
whose author typed "Telegram: @ skyluckwalker" with a space) and `_GLUED` (the same
contact written normally) both drive the model path — a bare handle is a bare
handle whether or not a regex can read it.
"""
from app.application.resolve_threads_lead import REVIEW_MODEL, resolve_threads_lead
from app.domain.lead import STATUS_NEW, Lead

_URL = "https://www.threads.com/@lnkrnchk/post/DbL4LxBl6v9"

_HEAD = ("Ищу Full Stack Developer (Lovable / Claude Code / AI-first).\n\n"
         "Что важно: опыт с Lovable, Claude Code, Cursor, Supabase.\n\n")

_UNAMBIGUOUS = _HEAD + "Для отклика присылайте портфолио на hr@skyluck.io"
_FULL = _HEAD + "Для отклика присылайте портфолио в Telegram: @ skyluckwalker"
_GLUED = _HEAD + "Для отклика присылайте портфолио в Telegram: @skyluckwalker"

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


# --- the rules path: unambiguous shapes only ------------------------------

def test_contact_found_in_the_thread_switches_the_platform():
    repo = FakeRepo()
    out, _ = resolve_threads_lead(_lead(), repo, render=lambda url: _UNAMBIGUOUS)
    assert out.platform == "email"
    assert out.target == "hr@skyluck.io"
    assert "Что важно" in out.vacancy_context


def test_contact_found_is_persisted_once():
    repo = FakeRepo()
    resolve_threads_lead(_lead(), repo, render=lambda url: _UNAMBIGUOUS)
    assert len(repo.resolved) == 1
    row, platform, target, text, note = repo.resolved[0]
    assert (row, platform, target) == (5, "email", "hr@skyluck.io")
    assert "Что важно" in text
    assert _URL in note, "в заметке должна остаться ссылка на исходный тред"


def test_an_unambiguous_shape_needs_no_cue():
    """Shape is the whole test. No apply words anywhere near it."""
    repo = FakeRepo()
    out, review = resolve_threads_lead(
        _lead(), repo, render=lambda url: "Ищем разработчика в Acme. hr@acme.io")
    assert (out.platform, out.target) == ("email", "hr@acme.io")
    assert review == ""


def test_a_tme_link_is_a_contact():
    repo = FakeRepo()
    out, review = resolve_threads_lead(
        _lead(), repo, render=lambda url: "Стек @nestjs. Наш канал https://t.me/acmejobs")
    assert (out.platform, out.target) == ("telegram", "https://t.me/acmejobs")
    assert review == ""


def test_an_hh_link_is_a_contact():
    repo = FakeRepo()
    out, review = resolve_threads_lead(
        _lead(), repo, render=lambda url: "Ищем разработчика. https://hh.ru/vacancy/135297431")
    assert out.platform == "hh" and review == ""


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


# --- a bare mention is never the recipient the rules pick ------------------
# Every text below yielded a confident Telegram contact from detect_contact, and
# every one of them points at somebody who is not hiring. Four rounds of cue
# heuristics could not separate these from genuine contact lines, because the
# difference is semantic. They are all held or resolved elsewhere now.

def _mention_never_wins(text, llm=None):
    """Resolve `text` and return (lead, review) after asserting no bare mention
    became the recipient on the rules' say-so."""
    out, review = resolve_threads_lead(_lead(), FakeRepo(),
                                       render=lambda url: text, llm=llm)
    if out.platform == "telegram" and out.target.startswith("@"):
        assert review == REVIEW_MODEL, (
            f"{text!r} -> {out.target} без проверки человеком")
    return out, review


def test_a_company_mention_in_prose_is_not_the_contact():
    """Round 3's probe 1."""
    out, _ = _mention_never_wins("Ищем разработчика в @acmecorp. Пишите в комментарии.")
    assert out.platform == "threads"


def test_a_thanks_mention_loses_to_the_real_email_further_down():
    """Round 3's probe 2 — the mention is stepped over, the email is the contact."""
    out, review = _mention_never_wins(
        "Спасибо @kollega за репост! Ищем разработчика. Резюме на hr@acme.io")
    assert (out.platform, out.target) == ("email", "hr@acme.io")
    assert review == ""


def test_a_stack_mention_is_not_a_contact():
    """Round 3's probe 3."""
    out, _ = _mention_never_wins("Стек: @nestjs и @supabase. Отклики в комментарии.")
    assert out.platform == "threads"


def test_a_mention_whose_neighbour_line_says_do_not_write_there():
    """Round 4's cue rule read this as vouched and sent to @kollega."""
    out, _ = _mention_never_wins("@kollega\nотклики принимаем только на сайте")
    assert out.platform == "threads"


def test_a_lone_mention_between_blank_lines_with_a_form_only_instruction():
    out, _ = _mention_never_wins(
        "Ищем разработчика\n\n@design_studio\n\nОтклики только через форму")
    assert out.platform == "threads"


def test_a_cue_ending_the_previous_line_no_longer_vouches():
    """Round 4 auto-sent this. It is a mention on a line after an apply word —
    indistinguishable in shape from the two tests above."""
    out, review = _mention_never_wins("Отклики:\n@hiring_acme")
    assert out.platform == "threads" and review == ""


def test_a_cue_opening_the_next_line_no_longer_vouches():
    out, _ = _mention_never_wins("@acme_hr\nпишите в личку")
    assert out.platform == "threads"


def test_the_captured_dm_me_span_shape_is_not_auto_sent():
    """From test_threads_post: post_body(["1 дн.","DM me:","@acme_hr","1"])."""
    out, _ = _mention_never_wins("DM me:\n@acme_hr")
    assert out.platform == "threads"


def test_an_inline_cue_no_longer_vouches_either():
    """The deliberate cost of the decision, stated as a test: a perfectly phrased
    contact line does not auto-send on the rules alone."""
    out, review = _mention_never_wins(
        "Ищем разработчика. Для отклика пишите в Telegram: @hiring_acme")
    assert out.platform == "threads" and review == ""


def test_a_perfectly_cued_mention_is_recovered_by_the_model_and_held():
    """…and with the model wired it is found, and held for a human."""
    out, review = _mention_never_wins(
        "Ищем разработчика. Для отклика пишите в Telegram: @hiring_acme",
        llm=lambda t: '{"platform": "telegram", "target": "@hiring_acme"}')
    assert (out.platform, out.target) == ("telegram", "@hiring_acme")
    assert review == REVIEW_MODEL


def test_a_bystander_mention_the_model_declines_stays_at_the_dm():
    """The model is asked, says there is no contact, and the DM fallback holds."""
    out, review = _mention_never_wins(
        "Спасибо @kollega за репост! Отклики только через форму.",
        llm=lambda t: '{"platform": null}')
    assert (out.platform, out.target) == ("threads", "@lnkrnchk")
    assert review == ""


def test_a_mention_competing_with_an_email_resolves_to_the_email():
    """Round 4 held this as ambiguous; now the mention simply never competes."""
    out, review = _mention_never_wins(
        "Резюме смотрел @kollega, он рекомендовал; hr@acme.io")
    assert (out.platform, out.target) == ("email", "hr@acme.io")
    assert review == ""


def test_a_handle_glued_to_a_tld_is_not_a_telegram_contact():
    """"Резюме на hr @acmecorp.com": _HANDLE_RE stops at the dot and the email rule
    never fires across the space, so this used to send to "@acmecorp"."""
    out, _ = _mention_never_wins("Резюме на hr @acmecorp.com")
    assert out.target != "@acmecorp"
    assert out.platform == "threads"


def test_the_address_behind_a_glued_handle_is_recovered_by_the_model():
    """Masking removes the at-sign, so no rule can rebuild "hr@acmecorp.com" —
    reading the spaced form is exactly what the model is for."""
    out, review = _mention_never_wins(
        "Резюме на hr @acmecorp.com",
        llm=lambda t: '{"platform": "email", "target": "hr@acmecorp.com"}')
    assert (out.platform, out.target) == ("email", "hr@acmecorp.com")
    assert review == REVIEW_MODEL


# --- the author -----------------------------------------------------------

def test_the_authors_own_handle_is_not_treated_as_a_telegram_contact():
    """"@lnkrnchk" written by @lnkrnchk in their own post is their THREADS name,
    not a Telegram username — DMing it would reach a different person."""
    repo = FakeRepo()
    text = "Ищем разработчика. Пишите мне @lnkrnchk, отвечаю быстро."
    out, _ = resolve_threads_lead(_lead(), repo, render=lambda url: text)
    assert out.platform == "threads"
    assert out.target == "@lnkrnchk"          # the DM fallback, not a Telegram DM


def test_the_model_cannot_hand_back_the_authors_handle_either():
    """The single remaining author guard: check 5 in parse_contact_response."""
    out, review = resolve_threads_lead(
        _lead(), FakeRepo(),
        render=lambda url: "Ищем разработчика. Пишите мне @ lnkrnchk.",
        llm=lambda t: '{"platform": "telegram", "target": "@lnkrnchk"}')
    assert (out.platform, out.target) == ("threads", "@lnkrnchk")
    assert review == ""


def test_masking_the_author_keeps_a_good_email_behind_it():
    repo = FakeRepo()
    text = "Я @lnkrnchk, ищем разработчика. Резюме на hr@acme.io"
    out, review = resolve_threads_lead(_lead(), repo, render=lambda url: text)
    assert (out.platform, out.target) == ("email", "hr@acme.io")
    assert review == ""


def test_masking_does_not_reach_inside_an_address():
    """"@nick" is masked; "hr@nick.com" is left alone."""
    from app.application.resolve_threads_lead import _mask_handle
    assert _mask_handle("пишите @lnkrnchk или hr@lnkrnchk.com", "@lnkrnchk") == \
        "пишите lnkrnchk или hr@lnkrnchk.com"


# --- failure paths: never lost, never skipped -----------------------------

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


def test_a_detector_that_raises_is_swallowed():
    """`detect` is an injectable seam and this function must never raise."""
    def boom(text):
        raise RuntimeError("bad regex")

    out, review = resolve_threads_lead(_lead(), FakeRepo(),
                                       render=lambda url: _UNAMBIGUOUS, detect=boom)
    assert (out.platform, out.target) == ("threads", "@lnkrnchk")
    assert review == ""


def test_a_persist_failure_still_returns_the_resolved_lead_in_memory():
    """Sheets being down must not cost us the send: the rewrite is a convenience,
    the in-memory lead is what the run uses."""
    class BrokenRepo(FakeRepo):
        def update_resolved(self, *a, **kw):
            raise RuntimeError("sheets 503")

    out, _ = resolve_threads_lead(_lead(), BrokenRepo(),
                                  render=lambda url: _UNAMBIGUOUS)
    assert out.platform == "email" and out.target == "hr@skyluck.io"


def test_a_persist_failure_is_reported_to_the_human(capsys):
    """Silently sending on a row that still says `threads` is a wrong record the
    human has to know about — it is only recoverable if they see it."""
    class BrokenRepo(FakeRepo):
        def update_resolved(self, *a, **kw):
            raise RuntimeError("sheets 503")

    resolve_threads_lead(_lead(), BrokenRepo(), render=lambda url: _UNAMBIGUOUS)
    out = capsys.readouterr().out
    assert "#7" in out and "таблиц" in out


def test_non_threads_leads_are_returned_as_is():
    repo = FakeRepo()
    lead = _lead(platform="hh", target="https://hh.ru/vacancy/1")
    called = []
    out, _ = resolve_threads_lead(lead, repo,
                                  render=lambda url: called.append(url) or "")
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
    """Rules first. An unambiguous shape never costs an OpenAI call."""
    asked = []
    out, _ = resolve_threads_lead(_lead(), FakeRepo(),
                                  render=lambda url: _UNAMBIGUOUS,
                                  llm=lambda text: asked.append(text) or _FOUND)
    assert asked == []
    assert out.target == "hr@skyluck.io"


def test_the_model_recovers_a_contact_the_rules_cannot_see():
    """The live case: "Telegram: @ skyluckwalker" — a space the author typed."""
    out, review = resolve_threads_lead(_lead(), FakeRepo(),
                                       render=lambda url: _FULL,
                                       llm=lambda text: _FOUND)
    assert (out.platform, out.target) == ("telegram", "@skyluckwalker")
    assert review == REVIEW_MODEL


def test_the_model_is_given_the_thread_text_with_mentions_unmasked():
    """The at-signs are the strongest signal that a mention IS a mention, and
    reading which one is the contact is the whole reason the model is asked. Uses
    the GLUED form on purpose: with the typed-space form nothing is masked, so this
    test would pass without testing anything."""
    asked = []
    resolve_threads_lead(_lead(), FakeRepo(), render=lambda url: _GLUED,
                         llm=lambda text: asked.append(text) or _FOUND)
    assert asked == [_GLUED]


def test_a_glued_handle_also_goes_through_the_model():
    """A bare handle is a bare handle whether or not a regex can read it."""
    out, review = resolve_threads_lead(_lead(), FakeRepo(),
                                       render=lambda url: _GLUED,
                                       llm=lambda text: _FOUND)
    assert (out.platform, out.target) == ("telegram", "@skyluckwalker")
    assert review == REVIEW_MODEL


def test_a_model_found_contact_is_marked_as_such_in_the_note():
    repo = FakeRepo()
    resolve_threads_lead(_lead(), repo, render=lambda url: _FULL,
                         llm=lambda text: _FOUND)
    note = repo.resolved[0][4]
    assert "модел" in note.lower() and _URL in note


def test_a_model_found_contact_is_announced_to_the_human(capsys):
    """It is a guess that passed validation, not a rule — the human approving the
    send in `make run` is told so before they press [s]."""
    resolve_threads_lead(_lead(), FakeRepo(), render=lambda url: _FULL,
                         llm=lambda text: _FOUND)
    assert "модел" in capsys.readouterr().out.lower()


def test_no_model_means_the_dm_fallback():
    out, review = resolve_threads_lead(_lead(), FakeRepo(), render=lambda url: _FULL)
    assert (out.platform, out.target) == ("threads", "@lnkrnchk")
    assert review == ""


def test_a_model_that_raises_falls_back_to_the_dm():
    def boom(text):
        raise RuntimeError("openai 429")

    out, _ = resolve_threads_lead(_lead(), FakeRepo(), render=lambda url: _FULL,
                                  llm=boom)
    assert (out.platform, out.target) == ("threads", "@lnkrnchk")


def test_a_model_answer_that_fails_validation_falls_back_to_the_dm():
    """An invented handle never becomes a recipient."""
    repo = FakeRepo()
    out, review = resolve_threads_lead(
        _lead(), repo, render=lambda url: _FULL,
        llm=lambda text: '{"platform": "telegram", "target": "@totally_made_up"}')
    assert (out.platform, out.target) == ("threads", "@lnkrnchk")
    assert repo.resolved[0][1] == "threads"
    assert review == "", "отброшенный ответ модели — это не контакт, требующий проверки"


# --- what this design still gets wrong ------------------------------------

def test_known_limit_any_unambiguous_shape_wins_even_a_bystanders():
    """DOCUMENTS A LIMIT, and states its real breadth.

    Shape decides, and shape cannot say WHOSE. Any unambiguous contact in the
    thread is taken — a channel link instead of the person who said to write to
    them, or a third party's address the author merely mentioned. It is NOT
    bounded to "the author's own published link": every case below points at
    somebody who is not hiring, and all of them auto-send.

    Not closable in the resolver without either re-ranking `detect_contact` (a
    reviewed mirror of the intake bot's rules, out of bounds here) or bringing back
    the text heuristics round 5 deleted. Whose-address is the same semantic
    question as which-mention, and the model is only asked when the rules find
    nothing at all.
    """
    def resolved(text):
        out, review = resolve_threads_lead(_lead(), FakeRepo(),
                                           render=lambda url: text)
        return out.platform, out.target, review

    # a channel, where the post says to write to a person
    assert resolved("Пишите @hr_acme\nили в канал https://t.me/acmejobs") == (
        "telegram", "https://t.me/acmejobs", "")
    # a bystander's channel, where applying goes through a form
    assert resolved("Спасибо @kollega за наводку, его канал t.me/kollega_blog.\n"
                    "Мы ищем разработчика, отклики через форму на сайте.") == (
        "telegram", "t.me/kollega_blog", "")
    # a bystander's LinkedIn — the residual is not a t.me quirk
    assert resolved("Резюме смотрел @kollega, его профиль linkedin.com/in/kollega. "
                    "Отклики через форму.") == (
        "linkedin", "https://www.linkedin.com/in/kollega", "")
