"""Квота модели кончилась посреди отклика — лид не сгорает в `failed`.

Ответы на вопросы форм (LinkedIn Easy Apply, Indeed Apply, внешние ATS, опросник
hh) пишет модель, и вызов идёт из самого канала, внутри `channel.send`. Отказ
по дневной квоте (`LLMQuotaExhausted`, см. app/domain/llm_quota.py) доходил до
`SendOutreach.execute` как любое другое исключение и становился `failed`: лид
навсегда выпадал из очереди, хотя с ним самим всё в порядке — модель вернётся
через сутки. Прогон при этом шёл дальше и сжигал так же каждый следующий лид с
вопросами.
"""
from app.application.send_outreach import SendOutreach
from app.domain.channel import OutreachContent
from app.domain.lead import Lead
from app.domain.llm_quota import LLMQuotaExhausted


class _Channel:
    name = "fake"
    body_limit = None
    needs_subject = False

    def __init__(self, exc):
        self._exc = exc

    def start(self): ...
    def stop(self): ...

    def send(self, target, content):
        raise self._exc


def _lead():
    return Lead(row=2, lead_id="1", platform="fake", target="@x",
                vacancy_context="v", raw_text="r", status="new")


def test_an_exhausted_quota_is_its_own_outcome_not_a_failure():
    note = "дневная квота gemini-3.5-flash-lite (500 запросов в сутки) исчерпана"
    result = SendOutreach(_Channel(LLMQuotaExhausted(note))).execute(
        _lead(), OutreachContent(body="hi"))

    assert result.quota_exhausted is True
    assert not result.ok
    assert (result.rate_limited, result.manual, result.invited) == (False, False, False)
    assert "gemini-3.5-flash-lite" in result.error


def test_any_other_error_is_still_a_plain_failure():
    result = SendOutreach(_Channel(ValueError("boom"))).execute(
        _lead(), OutreachContent(body="hi"))
    assert result.quota_exhausted is False and "boom" in result.error
