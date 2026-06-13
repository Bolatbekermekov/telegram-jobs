from app.infrastructure.openai_client import OpenAISummarizer


class _Msg:
    def __init__(self, content): self.message = type("M", (), {"content": content})


class _Resp:
    def __init__(self, content): self.choices = [_Msg(content)]


class _FakeClient:
    def __init__(self, content=None, raise_exc=None):
        self._content = content
        self._raise = raise_exc
        self.chat = type("C", (), {"completions": self})()

    def create(self, **kwargs):
        if self._raise:
            raise self._raise
        return _Resp(self._content)


def test_summarize_returns_vacancy_context():
    client = _FakeClient(content='{"vacancy_context": "Backend, remote, Python"}')
    s = OpenAISummarizer("key", "model", client=client)
    assert s.summarize("any text") == "Backend, remote, Python"


def test_summarize_returns_empty_on_error():
    client = _FakeClient(raise_exc=RuntimeError("boom"))
    s = OpenAISummarizer("key", "model", client=client)
    assert s.summarize("any text") == ""


def test_summarize_returns_empty_on_bad_json():
    client = _FakeClient(content="not json")
    s = OpenAISummarizer("key", "model", client=client)
    assert s.summarize("any text") == ""
