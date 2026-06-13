import pytest

from app.domain.channel import ChannelError, OutreachContent
from app.infrastructure.channels.headhunter import (
    HeadHunterChannel,
    extract_vacancy_id,
    post_negotiation,
)


def test_extract_vacancy_id_from_url():
    assert extract_vacancy_id("https://hh.ru/vacancy/12345?from=x") == "12345"
    assert extract_vacancy_id("12345") == "12345"


def test_extract_vacancy_id_invalid():
    with pytest.raises(ChannelError):
        extract_vacancy_id("https://hh.ru/employer/9")


def test_post_negotiation_sends_form():
    captured = {}

    class _FakeClient:
        def post(self, url, data=None):
            captured["url"] = url
            captured["data"] = data
            class _R:
                status_code = 201
                def json(self): return {}
            return _R()

    post_negotiation(_FakeClient(), resume_id="r1", vacancy_id="v1", message="hello")
    assert captured["url"].endswith("/negotiations")
    assert captured["data"] == {"vacancy_id": "v1", "resume_id": "r1", "message": "hello"}


def test_post_negotiation_raises_on_error_status():
    class _FakeClient:
        def post(self, url, data=None):
            class _R:
                status_code = 403
                text = "forbidden"
                def json(self): return {"errors": [{"value": "forbidden"}]}
            return _R()

    with pytest.raises(ChannelError):
        post_negotiation(_FakeClient(), resume_id="r1", vacancy_id="v1", message="hi")


def test_channel_metadata():
    ch = HeadHunterChannel(access_token="t", resume_id="r1")
    assert ch.name == "hh"
    assert ch.needs_subject is False
