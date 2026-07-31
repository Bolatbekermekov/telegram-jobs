"""The `invited` loop: a request went out without our letter, now what.

A lead reaches `invited` only when LinkedIn's monthly personalized-invite quota
was spent — the connection request reached the person, the cover letter did not.
Nothing moves it until they accept, so every run re-checks. States measured live
2026-07-29 on a real pending invite: the action bar shows «На рассмотрении» whose
aria-label offers to withdraw the invitation.
"""
import pytest

from app.domain.lead import (
    STATUS_FAILED, STATUS_INVITED, STATUS_MANUAL, STATUS_SENT, Lead,
)
from app.interface.cli import _followup_invited


def _lead(lead_id="79", platform="linkedin", target="https://linkedin.com/in/x"):
    return Lead(row=80, lead_id=lead_id, platform=platform, target=target,
                vacancy_context="Backend Engineer, Алматы", raw_text="",
                status=STATUS_INVITED)


class _Repo:
    def __init__(self, leads):
        self._leads = leads
        self.statuses = []
        self.sent = []
        self.vacancies = []

    def fetch_by_status(self, status):
        return list(self._leads) if status == STATUS_INVITED else []

    def mark_status(self, lead, status, note=""):
        self.statuses.append((lead.lead_id, status, note))

    def mark_sent(self, lead, message, status):
        self.sent.append((lead.lead_id, message, status))

    def update_vacancy(self, lead, vacancy_context):
        self.vacancies.append((lead.lead_id, vacancy_context))


class _Channel:
    name = "linkedin"
    body_limit = None
    needs_subject = False

    def __init__(self, state="accepted", send_error=None):
        self._state = state
        self._send_error = send_error
        self.sent = []
        self.checked = []

    def invite_state(self, target):
        self.checked.append(target)
        return self._state

    def send(self, target, content):
        if self._send_error:
            raise self._send_error
        self.sent.append((target, content))


class _Switcher:
    def __init__(self, channel):
        self._channel = channel

    def for_platform(self, platform):
        return self._channel


class _Generator:
    def __init__(self, body="Здравствуйте! Интересна ваша вакансия."):
        self._body = body

    def execute(self, lead):
        return self._body


def _run(repo, channel, generator=None):
    _followup_invited(repo, _Switcher(channel), generator or _Generator())


def test_a_pending_invite_is_left_alone():
    repo, channel = _Repo([_lead()]), _Channel(state="pending")
    _run(repo, channel)

    assert repo.statuses == []          # still `invited`
    assert repo.sent == []
    assert channel.sent == []


def test_an_accepted_invite_gets_the_letter_and_becomes_sent():
    repo, channel = _Repo([_lead()]), _Channel(state="accepted")
    _run(repo, channel)

    assert len(channel.sent) == 1
    (lead_id, body, status), = repo.sent
    assert (lead_id, status) == ("79", STATUS_SENT)
    assert "вакансия" in body.lower()


def test_an_accepted_invite_carries_the_cv(monkeypatch):
    """The one case LinkedIn lets us attach a file: a 1st-degree contact."""
    from app import config
    monkeypatch.setattr(config, "ATTACH_CV", True, raising=False)
    monkeypatch.setattr(config, "CV_PATH", "/cv/me.pdf", raising=False)
    repo, channel = _Repo([_lead()]), _Channel(state="accepted")
    _run(repo, channel)

    (_target, content), = channel.sent
    assert content.attachment_path == "/cv/me.pdf"


def test_a_vanished_invite_is_parked_for_a_human():
    """Declined, withdrawn or expired. Not `new`: re-inviting someone who already
    said no once is the human's call, not a thing to loop on."""
    repo, channel = _Repo([_lead()]), _Channel(state="gone")
    _run(repo, channel)

    (lead_id, status, note), = repo.statuses
    assert (lead_id, status) == ("79", STATUS_MANUAL)
    assert "приглашени" in note.lower()
    assert channel.sent == []


def test_a_failed_send_is_recorded_as_failed():
    repo = _Repo([_lead()])
    channel = _Channel(state="accepted", send_error=RuntimeError("composer gone"))
    _run(repo, channel)

    (lead_id, status, note), = repo.statuses
    assert (lead_id, status) == ("79", STATUS_FAILED)
    assert "composer gone" in note


def test_a_placeholder_holds_the_lead_instead_of_sending():
    repo, channel = _Repo([_lead()]), _Channel(state="accepted")
    _run(repo, channel, _Generator("Здравствуйте, [Название компании]!"))

    assert channel.sent == []
    assert repo.sent == []
    assert repo.statuses == []          # stays `invited`, re-rolled next run


def test_a_non_linkedin_invited_row_is_ignored():
    repo, channel = _Repo([_lead(platform="telegram", target="@x")]), _Channel()
    _run(repo, channel)

    assert channel.checked == []
    assert repo.statuses == []


def test_one_unreachable_profile_does_not_stop_the_rest():
    class _Flaky(_Channel):
        def invite_state(self, target):
            self.checked.append(target)
            if len(self.checked) == 1:
                raise RuntimeError("timeout")
            return "accepted"

    repo = _Repo([_lead("79"), _lead("80")])
    channel = _Flaky(state="accepted")
    _run(repo, channel)

    assert len(channel.checked) == 2
    assert [s[0] for s in repo.sent] == ["80"]


def test_no_invited_rows_means_no_channel_is_opened():
    class _Boom:
        def for_platform(self, platform):
            raise AssertionError("must not start a channel for nothing")

    _followup_invited(_Repo([]), _Boom(), _Generator())


# --- the bug this loop shipped with -----------------------------------------

def test_an_inmail_only_refusal_keeps_the_lead_invited():
    """LinkedIn saying "InMail only" IS the answer: they are not a contact, so the
    invite is still pending — whatever the profile page looked like. Leads
    141/143/144/145 were burned as `failed` this way on 2026-07-29."""
    from app.domain.channel import ManualApplyRequired

    repo = _Repo([_lead()])
    channel = _Channel(state="accepted",
                       send_error=ManualApplyRequired("LinkedIn: только InMail"))
    _run(repo, channel)

    assert repo.statuses == []          # stays `invited`
    assert repo.sent == []


# --- the letter is written from the vacancy, so the vacancy has to be real ----
#
# A lead sits in `invited` for days: by the time the person accepts, the stored
# vacancy text is the oldest thing we have about the job. The main send loop
# re-reads an unusable one before generating; this loop did not, and leads 159
# and 160 entered `invited` on 2026-07-29 carrying a model refusal in that column.

REFUSAL = ("Нет данных о вакансии в сообщении: предоставлена только ссылка "
           "без описания роли, формата работы, условий и зарплаты.")


@pytest.fixture
def fetcher(monkeypatch):
    """Replaces the network with a recorder; returns it."""
    from app.interface import cli

    calls = {"urls": [], "text": "Роль: Go-разработчик. Зарплата: 350 000 ₽."}
    monkeypatch.setattr(cli, "is_fetchable_vacancy_url", lambda url: True)
    monkeypatch.setattr(
        cli, "fetch_vacancy_text",
        lambda url, timeout=None: (calls["urls"].append(url), calls["text"])[1])
    return calls


def _invited_with(vacancy):
    lead = _lead()
    return type(lead)(**{**lead.__dict__, "vacancy_context": vacancy})


def test_a_refusal_in_the_column_is_re_read_before_the_letter(fetcher):
    repo, channel = _Repo([_invited_with(REFUSAL)]), _Channel(state="accepted")
    _run(repo, channel)

    assert fetcher["urls"] == ["https://linkedin.com/in/x"]
    assert repo.vacancies == [("79", fetcher["text"])]
    assert len(channel.sent) == 1


def test_an_unreadable_link_holds_the_lead_instead_of_writing_from_a_refusal(fetcher):
    fetcher["text"] = ""
    repo, channel = _Repo([_invited_with(REFUSAL)]), _Channel(state="accepted")
    _run(repo, channel)

    assert channel.sent == []
    assert repo.sent == []
    assert repo.statuses == []          # stays `invited`, retried next run


def test_a_usable_vacancy_is_never_re_read(fetcher):
    repo, channel = _Repo([_lead()]), _Channel(state="accepted")
    _run(repo, channel)

    assert fetcher["urls"] == []
    assert repo.vacancies == []
    assert len(channel.sent) == 1


def test_a_refusal_on_a_link_we_cannot_fetch_still_reaches_the_generator(monkeypatch):
    """No fetcher for this URL shape means nothing better is available; that is a
    separate problem from silently writing the letter from a refusal, and holding
    the lead forever would be worse than the placeholder net catching it."""
    from app.interface import cli
    monkeypatch.setattr(cli, "is_fetchable_vacancy_url", lambda url: False)

    repo, channel = _Repo([_invited_with(REFUSAL)]), _Channel(state="accepted")
    _run(repo, channel)

    assert repo.vacancies == []
    assert len(channel.sent) == 1


class _NoteChannel(_Channel):
    """Канал, который просит записку — как настоящий LinkedInChannel."""
    note_limit = 200


class _NoteGen:
    def execute(self, lead):
        return "Письмо."

    def execute_with_note(self, lead, note_limit):
        return "Полное письмо принявшему контакту.", "Короткая записка."


def test_the_accepted_contact_gets_the_whole_letter_and_the_note_rides_along():
    """Человек принял заявку, значит письмо идёт прямым сообщением и резать его
    нечем. Записка едет своим полем на случай, если канал пойдёт путём
    приглашения."""
    lead = _lead()
    repo = _Repo([lead])
    channel = _NoteChannel(state="accepted")
    _followup_invited(repo, _Switcher(channel), _NoteGen())

    (_target, content), = channel.sent
    assert content.body == "Полное письмо принявшему контакту."
    assert content.note == "Короткая записка."


class _PlaceholderNoteGen:
    def execute(self, lead):
        return "Письмо."

    def execute_with_note(self, lead, note_limit):
        return "Чистое письмо без шаблонов.", "Здравствуйте, [Имя]!"


def test_a_placeholder_in_the_note_holds_the_lead_back():
    """На этом пути нет ни AUTO_SEND, ни подтверждения человеком, поэтому шаблон
    в записке обязан останавливать отправку так же, как шаблон в письме."""
    lead = _lead()
    repo = _Repo([lead])
    channel = _NoteChannel(state="accepted")
    _followup_invited(repo, _Switcher(channel), _PlaceholderNoteGen())

    assert channel.sent == []
    assert repo.sent == []
