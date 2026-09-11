"""Канал `ats`: у прямой ссылки в ATS страница отклика и есть цель.

Отличие от канала агрегаторов ровно одно, и оно определяет весь класс. Агрегатор
не нанимает сам, поэтому `ExternalChannel` ищет на его странице единственную
осмысленную внешнюю ссылку и прыгает по ней на сайт работодателя. У Greenhouse
или Lever прыгать некуда: это уже сайт работодателя, форма либо на странице, либо
рисуется скриптом, либо лежит в iframe — и всё это `external_apply` разбирает сам
(`scrape_until_ready`, `_reveal_apply_form`, `_hop_to_embedded_form`).

Прогнать такую ссылку через поиск «единственной внешней ссылки» было бы хуже, чем
бесполезно: на странице Greenhouse внешних ссылок хватает (политика, соцсети,
сайт компании), и канал либо отдал бы лид в ручные, либо ушёл откликаться не
туда.
"""
import pytest

from app.domain.channel import ChannelError, OutreachContent
from app.infrastructure.channels.ats import AtsChannel

JOB = "https://boards.greenhouse.io/block/jobs/5406229008"
PAGE = f"""<html><head><title>Senior Go Engineer at Block</title></head>
<body><a href="https://block.xyz/privacy">Privacy</a>
<a href="https://twitter.com/block">tw</a>
<h1>Senior Go Engineer</h1>
<p>Build payment gateways in Go.</p>
<form><input type="file" name="resume"></form></body></html>"""


class _FakePage:
    def __init__(self, html=PAGE):
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
        class _Loc:
            @property
            def first(self_inner):
                return self_inner

            def inner_text(self_inner, timeout=None):
                return "Senior Go Engineer Block Build payment gateways in Go."

        return _Loc()


def _channel(page, **ext):
    deps = {"enabled": True, "fn": None, "cv_path": "/cv/default.pdf"}
    deps.update(ext)
    ch = AtsChannel(external_apply_deps=deps)
    ch._page = page          # обычно ставит start(); в тесте браузер не нужен
    return ch


def test_the_browser_goes_straight_to_the_vacancy():
    """Один переход, без промежуточного прыжка: это уже страница работодателя."""
    page = _FakePage()
    _channel(page, fn=lambda *a, **k: None).send(JOB, OutreachContent(body="привет"))
    assert page.visited == [JOB]


def test_the_form_is_handed_to_the_shared_apply_code():
    page = _FakePage()
    handed = {}

    def _apply(pg, job_url, content, **kw):
        handed["page"] = pg
        handed["job_url"] = job_url

    _channel(page, fn=_apply).send(JOB, OutreachContent(body="привет"))
    assert handed["page"] is page and handed["job_url"] == JOB


def test_the_description_is_read_before_the_form_is_touched():
    """Текст вакансии нужен, чтобы отвечать на вопросы работодателя в форме.

    У Ashby и Workable это ЕДИНСТВЕННЫЙ способ его получить: анонимный GET
    интейка возвращает по ним пустой React-шелл (замер 2026-09-11).
    """
    page = _FakePage()
    handed = {}
    _channel(page, fn=lambda pg, job_url, content, **kw: handed.update(
        ctx=kw.get("vacancy_context", ""))).send(JOB, OutreachContent(body="x"))
    assert "payment gateways" in handed["ctx"]


def test_the_cv_of_the_letters_role_beats_the_default():
    """Тот же стык уже чинили в LinkedIn, RemoteOK и агрегаторах."""
    page = _FakePage()
    handed = {}
    _channel(page, fn=lambda pg, job_url, content, **kw: handed.update(
        cv=kw.get("cv_path"))).send(
            JOB, OutreachContent(body="x", attachment_path="/cv/ai.pdf"))
    assert handed["cv"] == "/cv/ai.pdf"


def test_without_a_role_cv_the_default_is_used():
    page = _FakePage()
    handed = {}
    _channel(page, fn=lambda pg, job_url, content, **kw: handed.update(
        cv=kw.get("cv_path"))).send(JOB, OutreachContent(body="x"))
    assert handed["cv"] == "/cv/default.pdf"


def test_send_without_start_is_an_error_not_a_crash():
    ch = AtsChannel(external_apply_deps={"enabled": True, "fn": lambda *a, **k: None})
    with pytest.raises(ChannelError):
        ch.send(JOB, OutreachContent(body="x"))


def test_a_disabled_external_apply_says_so_and_names_the_switch():
    """У этой площадки другого пути нет: молчать об отключённом отклике нельзя."""
    page = _FakePage()
    ch = _channel(page, enabled=False)
    with pytest.raises(ChannelError, match="EXTERNAL_APPLY_ENABLED"):
        ch.send(JOB, OutreachContent(body="x"))


# --- регистрация площадки -------------------------------------------------

def test_the_registry_builds_it_with_the_shared_apply_code():
    """Без ветки в реестре лид падает на ValueError, и цикл читает это как
    сломанный канал — останавливается весь прогон, а не один лид."""
    from tests.test_registry import _Cfg
    from app.infrastructure.channels.registry import build_channel

    ch = build_channel("ats", _Cfg())
    assert isinstance(ch, AtsChannel)
    assert ch._ext.get("fn") is not None, "своей формы у площадки нет, отклик только внешний"


def test_the_send_loop_knows_the_platform():
    """Площадки нет в `_KNOWN` — и каждый её лид тихо уходит в `skipped`."""
    from app.interface.cli import _KNOWN
    assert "ats" in _KNOWN


def test_it_satisfies_the_channel_protocol():
    from app.domain.channel import OutreachChannel
    assert isinstance(AtsChannel(), OutreachChannel)
