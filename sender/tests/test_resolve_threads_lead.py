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
from app.application.resolve_threads_lead import resolve_threads_lead
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
    out = resolve_threads_lead(_lead(), repo, render=lambda url: _GLUED)
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
    out = resolve_threads_lead(_lead(), repo, render=lambda url: text)
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
    out = resolve_threads_lead(original, repo, render=lambda url: "")
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

    out = resolve_threads_lead(_lead(), repo, render=boom)
    assert out.platform == "threads" and repo.resolved == []


def test_a_persist_failure_still_returns_the_resolved_lead_in_memory():
    """Sheets being down must not cost us the send: the rewrite is a convenience,
    the in-memory lead is what the run uses."""
    class BrokenRepo(FakeRepo):
        def update_resolved(self, *a, **kw):
            raise RuntimeError("sheets 503")

    out = resolve_threads_lead(_lead(), BrokenRepo(), render=lambda url: _GLUED)
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
    out = resolve_threads_lead(_lead(), repo, render=lambda url: text)
    assert out.platform == "threads"
    assert out.target == "@lnkrnchk"          # the DM fallback, not a Telegram DM


def test_a_different_handle_in_the_authors_post_still_wins():
    repo = FakeRepo()
    text = "Ищем разработчика. Резюме в Telegram: @hiring_bot_hr"
    out = resolve_threads_lead(_lead(), repo, render=lambda url: text)
    assert out.platform == "telegram"
    assert out.target == "@hiring_bot_hr"


def test_non_threads_leads_are_returned_as_is():
    repo = FakeRepo()
    lead = _lead(platform="hh", target="https://hh.ru/vacancy/1")
    called = []
    out = resolve_threads_lead(lead, repo, render=lambda url: called.append(url) or "")
    assert out is lead and called == []


def test_shorter_resolved_text_does_not_replace_a_longer_stored_one():
    """A partial render (hydration lost a reply) must not shrink the vacancy."""
    repo = FakeRepo()
    lead = _lead(vacancy_context="a" * 900)
    out = resolve_threads_lead(lead, repo, render=lambda url: "короткий огрызок")
    assert out.vacancy_context == "a" * 900


def test_an_empty_target_leaves_the_row_alone():
    """update_resolved blanks Источник while setting Платформа, and skip_reason
    gates only on the platform — a blank target means the NEXT run opens a channel
    and sends to "". Nothing to point at means: do not rewrite the row."""
    repo = FakeRepo()
    lead = _lead(target="")
    out = resolve_threads_lead(lead, repo, render=lambda url: "Ищем разработчика.")
    assert out is lead
    assert repo.resolved == [] and repo.statuses == []


# --- the model fallback ---------------------------------------------------

def test_the_model_is_not_asked_when_the_rules_found_a_contact():
    """Rules decide first. Every pre-existing lead keeps its deterministic path."""
    repo = FakeRepo()
    asked = []

    out = resolve_threads_lead(_lead(), repo, render=lambda url: _GLUED,
                               llm=lambda text: asked.append(text) or _FOUND)
    assert asked == []
    assert out.target == "@skyluckwalker"


def test_the_model_recovers_a_contact_the_rules_cannot_see():
    """The live case: "Telegram: @ skyluckwalker" — a space the author typed."""
    repo = FakeRepo()
    out = resolve_threads_lead(_lead(), repo, render=lambda url: _FULL,
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
    out = resolve_threads_lead(_lead(), repo, render=lambda url: _FULL)
    assert (out.platform, out.target) == ("threads", "@lnkrnchk")


def test_a_model_that_raises_falls_back_to_the_dm():
    repo = FakeRepo()

    def boom(text):
        raise RuntimeError("openai 429")

    out = resolve_threads_lead(_lead(), repo, render=lambda url: _FULL, llm=boom)
    assert (out.platform, out.target) == ("threads", "@lnkrnchk")


def test_a_model_answer_that_fails_validation_falls_back_to_the_dm():
    """An invented handle never becomes a recipient."""
    repo = FakeRepo()
    out = resolve_threads_lead(
        _lead(), repo, render=lambda url: _FULL,
        llm=lambda text: '{"platform": "telegram", "target": "@totally_made_up"}')
    assert (out.platform, out.target) == ("threads", "@lnkrnchk")
    assert repo.resolved[0][1] == "threads"


def test_the_model_cannot_hand_back_the_authors_handle_as_telegram():
    repo = FakeRepo()
    text = "Ищем разработчика. Пишите мне @ lnkrnchk, отвечаю быстро."
    out = resolve_threads_lead(
        _lead(), repo, render=lambda url: text,
        llm=lambda t: '{"platform": "telegram", "target": "@lnkrnchk"}')
    assert (out.platform, out.target) == ("threads", "@lnkrnchk")


def test_the_model_still_runs_after_the_rules_hit_only_the_author():
    """The rule guard nulls the author's handle; the model then gets its chance
    at the contact the rules could not glue."""
    repo = FakeRepo()
    text = ("Ищем разработчика. Я @lnkrnchk, автор поста.\n"
            "Отклики в телеграм: @ hiring_acme")
    out = resolve_threads_lead(
        _lead(), repo, render=lambda url: text,
        llm=lambda t: '{"platform": "telegram", "target": "@hiring_acme"}')
    assert (out.platform, out.target) == ("telegram", "@hiring_acme")
