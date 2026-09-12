"""Канал Jobicy: пройти регистрационный гейт и отдать форму работодателя общему коду.

Замер живьём 2026-09-11 объясняет, почему канал вообще нужен и почему он такой.
Кнопка «Apply Now» на странице вакансии — НЕ ссылка: это `<button>` с
`aria-haspopup="dialog"` и событием `RegistrationGateOpened`. Адреса работодателя
нет ни в разметке страницы, ни в пред-отрисованном попапе, ни в `jobDescription`
(проверено на 50 вакансиях: ноль ссылок в ATS). Jobicy отдаёт его только
зарегистрированным — значит нужен аккаунт и сохранённая сессия, как у RemoteOK.

Пока сессии нет, канал обязан отвечать `ChannelUnavailable`, а не `ChannelError`:
разница в том, что лиды остаются `new` и дождутся входа, вместо того чтобы
сгореть в `failed` пачкой.

И главное правило: если после клика мы всё ещё на jobicy.com, канал НЕ гадает,
куда идти. На странице десятки внешних ссылок (соцсети, магазины приложений,
реклама), и выбор наугад — это отклик в чужую вакансию. Такой лид уходит в руки.
"""
import pytest

from app.domain.channel import (
    ChannelError, ChannelUnavailable, ManualApplyRequired, OutreachContent,
)
from app.infrastructure.channels.jobicy import JobicyChannel

JOB = "https://jobicy.com/jobs/150364-software-engineer-python-container-images"
ATS = "https://boards.greenhouse.io/canonical/jobs/5406229008"


class _FakePage:
    """Страница, которая после клика по «Apply Now» уезжает на `lands_on`."""

    def __init__(self, lands_on=ATS):
        self.url = ""
        self.visited = []
        self.clicked = []
        self._lands_on = lands_on

    def goto(self, url, **kw):
        self.visited.append(url)
        self.url = url

    def wait_for_timeout(self, ms):
        pass

    def locator(self, selector):
        page = self

        class _Loc:
            @property
            def first(self_inner):
                return self_inner

            def count(self_inner):
                return 1

            def click(self_inner, timeout=None):
                page.clicked.append(selector)
                if page._lands_on:
                    page.url = page._lands_on

            def inner_text(self_inner, timeout=None):
                return "Software Engineer Python Canonical Build container images."

        return _Loc()


def _channel(page, **ext):
    deps = {"enabled": True, "fn": lambda *a, **k: None, "cv_path": "/cv/default.pdf"}
    deps.update(ext)
    ch = JobicyChannel("jobicy_state.json", external_apply_deps=deps)
    ch._page = page          # обычно ставит start(); в тесте браузер не нужен
    return ch


def test_without_a_session_the_leads_wait_instead_of_burning():
    """`ChannelUnavailable`, а не `ChannelError`: лиды остаются `new`."""
    ch = JobicyChannel("нет-такого-файла.json")
    with pytest.raises(ChannelUnavailable, match="login_jobicy"):
        ch.start()


def test_send_without_start_is_an_error_not_a_crash():
    ch = JobicyChannel("jobicy_state.json")
    with pytest.raises(ChannelError):
        ch.send(JOB, OutreachContent(body="x"))


def test_a_disabled_external_apply_says_so_and_names_the_switch():
    ch = _channel(_FakePage(), enabled=False)
    with pytest.raises(ChannelError, match="EXTERNAL_APPLY_ENABLED"):
        ch.send(JOB, OutreachContent(body="x"))


def test_the_vacancy_is_opened_and_the_apply_gate_is_clicked():
    page = _FakePage()
    _channel(page).send(JOB, OutreachContent(body="привет"))
    assert page.visited == [JOB]
    assert page.clicked, "гейт не нажат — до формы работодателя не дойти"


def test_the_employer_page_is_handed_to_the_shared_apply_code():
    page = _FakePage()
    handed = {}
    _channel(page, fn=lambda pg, job_url, content, **kw: handed.update(
        landed=pg.url, job_url=job_url)).send(JOB, OutreachContent(body="x"))
    assert handed["landed"] == ATS
    assert handed["job_url"] == JOB, "человеку показываем ссылку, что лежит в таблице"


def test_the_description_is_read_before_leaving_the_board():
    """Дальше страницы Jobicy уже нет, а текст нужен для ответов в чужой форме."""
    page = _FakePage()
    handed = {}
    _channel(page, fn=lambda pg, job_url, content, **kw: handed.update(
        ctx=kw.get("vacancy_context", ""))).send(JOB, OutreachContent(body="x"))
    assert "container images" in handed["ctx"]


def test_the_cv_of_the_letters_role_beats_the_default():
    page = _FakePage()
    handed = {}
    _channel(page, fn=lambda pg, job_url, content, **kw: handed.update(
        cv=kw.get("cv_path"))).send(
            JOB, OutreachContent(body="x", attachment_path="/cv/ai.pdf"))
    assert handed["cv"] == "/cv/ai.pdf"


def test_staying_on_the_board_hands_the_lead_over_instead_of_guessing():
    """Клик не увёл никуда: гейт не пройден, либо разметка сменилась.

    Выбирать «похожую» внешнюю ссылку тут нельзя — их на странице десятки
    (соцсети, магазины приложений, реклама), и промах означает отклик в чужую
    вакансию. Тот же принцип, что у канала агрегаторов.
    """
    page = _FakePage(lands_on=None)
    called = []
    with pytest.raises(ManualApplyRequired, match="jobicy.com/jobs/150364"):
        _channel(page, fn=lambda *a, **k: called.append(1)).send(
            JOB, OutreachContent(body="x"))
    assert called == [], "внешний отклик не должен вызываться вслепую"


def test_the_registry_builds_it_and_the_send_loop_knows_it():
    from app.interface.cli import _KNOWN
    from app.infrastructure.channels.registry import build_channel
    from tests.test_registry import _Cfg

    assert "jobicy" in _KNOWN, "иначе каждый лид площадки тихо уйдёт в skipped"
    ch = build_channel("jobicy", _Cfg())
    assert isinstance(ch, JobicyChannel)
    assert ch._ext.get("fn") is not None


def test_it_satisfies_the_channel_protocol():
    from app.domain.channel import OutreachChannel
    assert isinstance(JobicyChannel("s.json"), OutreachChannel)
