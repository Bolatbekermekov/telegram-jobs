"""Канал отклика RemoteOK: пройти редирект и отдать страницу external_apply.

Своей логики заполнения тут нет и не должно быть — обе дороги, куда приводит
Apply (форма ATS и почта работодателя), уже закрыты external_apply. Этот файл
проверяет ровно стык: что до него доходит и что до него НЕ доходит.
"""
import pytest

from app.domain.channel import ChannelError, ManualApplyRequired, OutreachContent
from app.infrastructure.channels.remoteok import RemoteOKChannel

JOB = "https://remoteok.com/remote-jobs/remote-junior-designer-haystack-1135900"


class _Loc:
    def __init__(self, text=""):
        self._text = text
        self.first = self

    def inner_text(self, timeout=None):
        return self._text


class _Page:
    """Страница, которая после перехода на /l/<id> оказывается на `lands_on`."""

    def __init__(self, lands_on):
        self._lands_on = lands_on
        self.url = ""
        self.goto_urls = []
        self.evaluated = []

    def goto(self, url, wait_until=None, timeout=None):
        self.goto_urls.append(url)
        self.url = url

    def evaluate(self, js, arg=None):
        self.evaluated.append(js)
        self.url = self._lands_on
        return None

    def wait_for_timeout(self, ms):
        pass

    def locator(self, sel):
        return _Loc("описание вакансии из RemoteOK")


def _channel(page, **ext):
    calls = []

    def fake_external_apply(page_, job_url, content, **kw):
        calls.append({"page": page_, "job_url": job_url, "content": content, **kw})

    deps = {"enabled": True, "fn": fake_external_apply, "profile": "ПРОФИЛЬ",
            "cv_path": "/cv/fullstack.pdf", "answerer": None, "dry_run": False,
            "email_channel": object(), "subject_maker": lambda v: "Тема"}
    deps.update(ext)
    ch = RemoteOKChannel("/нет/state.json", headless=True, external_apply_deps=deps)
    ch._page = page          # start() поднял бы настоящий браузер
    return ch, calls


CONTENT = OutreachContent(body="Здравствуйте! Интересна ваша вакансия.",
                          attachment_path="/cv/backend-go.pdf")


def test_the_apply_redirect_is_taken_from_the_job_page():
    """Относительной ссылкой и именно со страницы вакансии: без Referer RemoteOK
    отвечает 302 обратно, и отклик не открывается."""
    page = _Page("https://jobs.ashbyhq.com/superplane/ee9d219f")
    ch, calls = _channel(page)
    ch.send(JOB, CONTENT)

    assert page.goto_urls == [JOB]
    assert "/l/1135900" in page.evaluated[0]
    assert len(calls) == 1


def test_the_landed_page_is_what_external_apply_gets():
    """Не страница вакансии, а та, куда привёл редирект: заполнять надо форму
    работодателя."""
    page = _Page("https://jobs.ashbyhq.com/superplane/ee9d219f")
    ch, calls = _channel(page)
    ch.send(JOB, CONTENT)

    assert calls[0]["page"] is page
    assert page.url == "https://jobs.ashbyhq.com/superplane/ee9d219f"


def test_the_cv_of_the_chosen_role_wins_over_the_default():
    """Тот же стык, что уже чинили в LinkedIn: cv_path из вложения, а не из
    конфига — иначе на любую роль уходит одно и то же резюме."""
    page = _Page("https://jobs.ashbyhq.com/superplane/ee9d219f")
    ch, calls = _channel(page)
    ch.send(JOB, CONTENT)

    assert calls[0]["cv_path"] == "/cv/backend-go.pdf"


def test_without_an_attachment_the_default_cv_is_used():
    page = _Page("https://jobs.ashbyhq.com/superplane/ee9d219f")
    ch, calls = _channel(page)
    ch.send(JOB, OutreachContent(body="письмо"))

    assert calls[0]["cv_path"] == "/cv/fullstack.pdf"


def test_the_vacancy_text_is_read_before_leaving_the_job_page():
    """Он нужен, чтобы отвечать на вопросы работодателя в форме ATS. После
    перехода читать уже нечего — страницы вакансии больше нет."""
    page = _Page("https://jobs.ashbyhq.com/superplane/ee9d219f")
    ch, calls = _channel(page)
    ch.send(JOB, CONTENT)

    assert calls[0]["vacancy_context"] == "описание вакансии из RemoteOK"


def test_the_premium_wall_never_reaches_external_apply():
    """Заполнять там нечего, а «форма не распознана» увела бы человека не туда."""
    page = _Page("https://remoteok.com/premium?skip_url=x")
    ch, calls = _channel(page)

    with pytest.raises(ManualApplyRequired) as e:
        ch.send(JOB, CONTENT)

    assert calls == []
    assert "Premium" in str(e.value)


def test_a_dead_session_says_which_command_fixes_it():
    page = _Page("https://remoteok.com/sign-up?user_type=worker")
    ch, calls = _channel(page)

    with pytest.raises(ManualApplyRequired) as e:
        ch.send(JOB, CONTENT)

    assert calls == []
    assert "login_remoteok" in str(e.value)


def test_a_link_without_a_job_id_is_a_lead_level_failure():
    page = _Page("https://jobs.ashbyhq.com/x")
    ch, calls = _channel(page)

    with pytest.raises(ChannelError):
        ch.send("https://remoteok.com/remote-jobs", CONTENT)

    assert calls == []
    assert page.goto_urls == []


def test_send_without_start_does_not_pretend_to_work():
    ch = RemoteOKChannel("/нет/state.json", headless=True)
    with pytest.raises(ChannelError):
        ch.send(JOB, CONTENT)
