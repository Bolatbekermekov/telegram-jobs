"""Канал Indeed: пройти редирект площадки и отдать форму работодателя общему коду.

Гибрид двух существующих каналов, и оба заимствования вынужденные.

Транспорт — от Wellfound: подключение по CDP к Chrome, который человек поднял
`make login_indeed`. Своим браузером Indeed не открыть, там Cloudflare (замер
2026-09-12: обычный клиент 403, живой Chrome 200 и 32 карточки).

Тело отправки — от RemoteOK: открыть вакансию, прочитать описание ДО перехода,
пройти редирект относительной ссылкой, проверить, куда приземлились, и только
потом отдать страницу в `external_apply`. Адрес работодателя в разметке не
лежит, он раскрывается переходом.

Отличие от обоих: работаем в СВОЕЙ вкладке. Wellfound берёт тёплую вкладку
человека, но там отклик заполняется на самой площадке; здесь он уводит на чужие
сайты, и делать это во вкладке, в которой человек работает, нельзя.
"""
import pytest

from app.domain.channel import (
    ChannelError, ChannelUnavailable, ManualApplyRequired, OutreachContent,
)
from app.infrastructure.channels.indeed import IndeedChannel

JOB = "https://www.indeed.com/viewjob?jk=591fcde7d2cf0699"
ATS = "https://boards.greenhouse.io/acme/jobs/123"


class _FakePage:
    def __init__(self, lands_on=ATS):
        self.url = ""
        self.visited = []
        self.evaluated = []
        self.closed = False
        self._lands_on = lands_on

    def goto(self, url, **kw):
        self.visited.append(url)
        self.url = url

    def evaluate(self, script):
        self.evaluated.append(script)
        if self._lands_on:
            self.url = self._lands_on

    def wait_for_timeout(self, ms):
        pass

    def close(self):
        self.closed = True

    def locator(self, selector):
        class _Loc:
            @property
            def first(self_inner):
                return self_inner

            def inner_text(self_inner, timeout=None):
                return "AI Engineer at Acme. Build LLM agents in production."

        return _Loc()


def _channel(page, **ext):
    deps = {"enabled": True, "fn": lambda *a, **k: None, "cv_path": "/cv/default.pdf"}
    deps.update(ext)
    ch = IndeedChannel("http://127.0.0.1:9226", external_apply_deps=deps)
    ch._page = page          # обычно ставит start(); в тесте браузер не нужен
    return ch


# --- отказы до всякой навигации -------------------------------------------

def test_send_without_start_is_an_error_not_a_crash():
    ch = IndeedChannel("http://127.0.0.1:9226")
    with pytest.raises(ChannelError):
        ch.send(JOB, OutreachContent(body="x"))


def test_a_disabled_external_apply_says_so_and_names_the_switch():
    """У площадки нет своей формы: без внешнего отклика идти некуда."""
    with pytest.raises(ChannelError, match="EXTERNAL_APPLY_ENABLED"):
        _channel(_FakePage(), enabled=False).send(JOB, OutreachContent(body="x"))


def test_a_link_without_a_job_key_is_refused_before_the_browser_moves():
    page = _FakePage()
    with pytest.raises(ChannelError):
        _channel(page).send("https://www.indeed.com/jobs?q=ai", OutreachContent(body="x"))
    assert page.visited == [], "ходить некуда — и не ходим"


# --- нормальный путь ------------------------------------------------------

def test_the_vacancy_is_opened_and_the_redirect_is_followed():
    page = _FakePage()
    _channel(page).send(JOB, OutreachContent(body="привет"))
    assert page.visited == [JOB]
    assert page.evaluated, "переход идёт из страницы, чтобы уцелел Referer"
    assert "591fcde7d2cf0699" in page.evaluated[0]


def test_the_employer_page_is_handed_to_the_shared_apply_code():
    page = _FakePage()
    handed = {}
    _channel(page, fn=lambda pg, job_url, content, **kw: handed.update(
        landed=pg.url, job_url=job_url)).send(JOB, OutreachContent(body="x"))
    assert handed["landed"] == ATS
    assert handed["job_url"] == JOB, "человеку показываем ссылку из таблицы"


def test_the_description_is_read_before_the_redirect():
    """Дальше страницы Indeed уже нет, а текст нужен для ответов в чужой форме."""
    page = _FakePage()
    handed = {}
    _channel(page, fn=lambda pg, job_url, content, **kw: handed.update(
        ctx=kw.get("vacancy_context", ""))).send(JOB, OutreachContent(body="x"))
    assert "LLM agents" in handed["ctx"]


def test_the_cv_of_the_letters_role_beats_the_default():
    page = _FakePage()
    handed = {}
    _channel(page, fn=lambda pg, job_url, content, **kw: handed.update(
        cv=kw.get("cv_path"))).send(
            JOB, OutreachContent(body="x", attachment_path="/cv/ai.pdf"))
    assert handed["cv"] == "/cv/ai.pdf"


# --- стены Indeed ---------------------------------------------------------

def test_indeed_apply_goes_to_the_human_instead_of_the_form():
    """Форма живёт на самом Indeed, ATS за ней нет — заполнять нечего."""
    page = _FakePage(lands_on="https://www.indeed.com/applystart?jk=591fcde7d2cf0699")
    called = []
    with pytest.raises(ManualApplyRequired, match="Indeed Apply"):
        _channel(page, fn=lambda *a, **k: called.append(1)).send(
            JOB, OutreachContent(body="x"))
    assert called == [], "вслепую не заполняем"


def test_a_login_wall_names_the_fixing_command():
    page = _FakePage(lands_on="https://secure.indeed.com/account/login")
    with pytest.raises(ManualApplyRequired, match="login_indeed"):
        _channel(page).send(JOB, OutreachContent(body="x"))


# --- жизненный цикл браузера ----------------------------------------------

def test_a_dead_port_leaves_the_leads_alive():
    """`ChannelUnavailable`, а не `ChannelError`: лиды остаются `new`."""
    ch = IndeedChannel("http://127.0.0.1:59999")
    with pytest.raises(ChannelUnavailable, match="login_indeed"):
        ch.start()


def test_stop_closes_our_tab_and_not_the_users_browser():
    page = _FakePage()
    ch = _channel(page)
    ch.stop()
    assert page.closed is True


def test_it_satisfies_the_channel_protocol():
    from app.domain.channel import OutreachChannel
    assert isinstance(IndeedChannel("http://127.0.0.1:9226"), OutreachChannel)
