"""Канал `external`: довести браузер от агрегатора до формы работодателя.

Агрегатор вакансий не нанимает сам — он ведёт на сайт компании. Замер живьём
2026-08-22 на `remocate.app/jobs/software-engineering-intern-winter-datadog`:
среди восьми внешних хостов страницы семь это шум (CDN Webflow, шрифты Google,
соцсети и поддомены самого агрегатора), а осмысленный ровно один —
`careers.datadoghq.com`, настоящий адрес отклика.

Своей логики заполнения здесь нет и быть не должно: то, что лежит за этой
ссылкой, уже умеет разбирать `external_apply` — он же обслуживает внешние
отклики LinkedIn и RemoteOK. Задача канала — дойти до нужной страницы и не
уткнуться в стену молча.

Сессия каналу не нужна: страницы агрегаторов публичные, логина не просят. Этим
он отличается и от RemoteOK (сохранённое состояние), и от Wellfound (CDP ради
Cloudflare).
"""
import pytest

from app.domain.channel import ChannelError, ManualApplyRequired, OutreachContent
from app.infrastructure.channels.external import ExternalChannel

JOB = "https://www.remocate.app/jobs/software-engineering-intern-winter-datadog"
APPLY = "https://careers.datadoghq.com/detail/8052095/?gh_jid=8052095"

PAGE = f"""<html><head><title>Software Engineering Intern (Winter) at Datadog</title></head>
<body><a href="https://cdn.prod.website-files.com/x.svg">logo</a>
<a href="https://twitter.com/remocate">tw</a>
<a href="https://remocate.lemonsqueezy.com/checkout">pay</a>
<h1>Software Engineering Intern</h1><div>Datadog</div>
<p>Build and scale observability systems.</p>
<a href="{APPLY}">Apply for this job</a></body></html>"""

AMBIGUOUS = PAGE.replace("<h1>", '<a href="https://jobs.lever.co/other/1">x</a><h1>')


class _FakePage:
    def __init__(self, html):
        self._html = html
        self.url = ""
        self.visited = []

    def goto(self, url, **kw):
        self.visited.append(url)
        self.url = url

    def wait_for_timeout(self, ms):
        pass

    def content(self):
        return self._html

    def locator(self, selector):
        page = self

        class _Loc:
            @property
            def first(self_inner):
                return self_inner

            def inner_text(self_inner, timeout=None):
                return "Software Engineering Intern Datadog Build and scale"

        return _Loc()


def _channel(page, **ext):
    deps = {"enabled": True, "fn": None}
    deps.update(ext)
    ch = ExternalChannel(external_apply_deps=deps)
    ch._page = page          # обычно ставит start(); в тесте браузер не нужен
    return ch


def test_the_browser_is_walked_to_the_employer_page():
    page = _FakePage(PAGE)
    handed = {}

    def _apply(pg, job_url, content, **kw):
        handed["url"] = pg.url
        handed["job_url"] = job_url
        handed["context"] = kw.get("vacancy_context", "")

    _channel(page, fn=_apply).send(JOB, OutreachContent(body="здравствуйте"))

    assert page.visited == [JOB, APPLY]
    assert handed["url"] == APPLY


def test_the_lead_keeps_pointing_at_the_link_we_were_given():
    """`job_url` уходит дальше нетронутым: именно его показывают человеку, когда
    отклик просит рук, и именно он лежит в таблице."""
    page = _FakePage(PAGE)
    handed = {}
    _channel(page, fn=lambda pg, job_url, content, **kw: handed.update(job_url=job_url)) \
        .send(JOB, OutreachContent(body="здравствуйте"))

    assert handed["job_url"] == JOB


def test_the_description_is_read_before_leaving_the_page():
    """Дальше страницы агрегатора уже нет, а текст нужен, чтобы отвечать на
    вопросы работодателя в чужой форме. Тот же порядок, что в RemoteOK."""
    page = _FakePage(PAGE)
    handed = {}
    _channel(page, fn=lambda pg, job_url, content, **kw: handed.update(
        ctx=kw.get("vacancy_context", ""))).send(JOB, OutreachContent(body="x"))

    assert "Datadog" in handed["ctx"]


def test_an_ambiguous_page_is_left_for_a_human():
    """Два разных работодателя на странице — выбирать нельзя. Тот же принцип,
    что у точки входа Easy Apply, где угадывание уводило прогон в чужую вакансию."""
    page = _FakePage(AMBIGUOUS)

    with pytest.raises(ManualApplyRequired, match="не смог однозначно"):
        _channel(page, fn=lambda *a, **k: None).send(JOB, OutreachContent(body="x"))

    assert page.visited == [JOB]          # никуда не ушли


def test_a_page_without_an_employer_link_is_left_for_a_human():
    page = _FakePage(PAGE.replace(APPLY, "https://www.remocate.app/jobs/other"))

    with pytest.raises(ManualApplyRequired):
        _channel(page, fn=lambda *a, **k: None).send(JOB, OutreachContent(body="x"))


def test_auto_apply_switched_off_is_said_out_loud():
    page = _FakePage(PAGE)

    with pytest.raises(ChannelError, match="EXTERNAL_APPLY_ENABLED"):
        _channel(page, enabled=False, fn=None).send(JOB, OutreachContent(body="x"))


def test_sending_without_start_is_an_error_not_a_crash():
    ch = ExternalChannel(external_apply_deps={"enabled": True, "fn": lambda *a, **k: None})

    with pytest.raises(ChannelError, match="start"):
        ch.send(JOB, OutreachContent(body="x"))


def test_the_role_specific_cv_is_the_one_that_travels():
    """Тот же стык уже чинили в LinkedIn и RemoteOK: без этого на любую роль
    уходит резюме из конфига, а не то, под которое написано письмо."""
    page = _FakePage(PAGE)
    handed = {}
    _channel(page, fn=lambda pg, job_url, content, **kw: handed.update(cv=kw.get("cv_path")),
             cv_path="/конфиг.pdf").send(
        JOB, OutreachContent(body="x", attachment_path="/под-роль.pdf"))

    assert handed["cv"] == "/под-роль.pdf"
