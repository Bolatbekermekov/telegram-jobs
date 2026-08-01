"""Which model each OpenAI call uses, and that replies are length-capped.

Scoring runs on every job on every platform on every search; writing runs once
per lead. Sending both to the same model is what made the bill ~25x larger than
it needed to be, so the split is worth pinning down.
"""
from app.infrastructure.openai_client import OpenAIMessageGenerator
from app.infrastructure.openai_relevance import OpenAIRelevanceScorer
from app.infrastructure.openai_role import OpenAIRoleClassifier


class _FakeCompletions:
    def __init__(self, content):
        self.calls = []
        self._content = content

    def create(self, **kw):
        self.calls.append(kw)

        class _Msg:
            content = self._content

        class _Choice:
            message = _Msg()

        class _Resp:
            choices = [_Choice()]

        return _Resp()


class _FakeClient:
    def __init__(self, content):
        self.chat = type("_Chat", (), {"completions": _FakeCompletions(content)})()


def _generator(content="письмо", **kw):
    gen = OpenAIMessageGenerator.__new__(OpenAIMessageGenerator)
    gen._client = _FakeClient(content)
    gen._model = kw.get("model", "writing-model")
    gen._max_output_tokens = kw.get("max_output_tokens", 2000)
    return gen


def _scorer(content='{"score": 80, "reason": "ok"}', **kw):
    s = OpenAIRelevanceScorer.__new__(OpenAIRelevanceScorer)
    s._client = _FakeClient(content)
    s._model = kw.get("model", "cheap-model")
    s._max_output_tokens = kw.get("max_output_tokens", 2000)
    return s


def _classifier(content='{"role": "backend-go"}', **kw):
    c = OpenAIRoleClassifier.__new__(OpenAIRoleClassifier)
    c._client = _FakeClient(content)
    c._model = kw.get("model", "cheap-model")
    c._max_output_tokens = kw.get("max_output_tokens", 2000)
    return c


# --- model routing ----------------------------------------------------------

def test_scoring_uses_the_model_it_was_given():
    s = _scorer(model="gpt-5.4-nano")
    s.score("профиль", "Junior .NET", "описание вакансии")

    (kw,) = s._client.chat.completions.calls
    assert kw["model"] == "gpt-5.4-nano"


def test_writing_uses_the_model_it_was_given():
    gen = _generator(model="gpt-5.4-mini")
    gen.generate(cv_text="cv", profile_text="profile", vacancy_context="вакансия")

    (kw,) = gen._client.chat.completions.calls
    assert kw["model"] == "gpt-5.4-mini"


def test_scoring_and_writing_can_use_different_models():
    """The whole point of the split — one bill driver, one quality driver."""
    s, gen = _scorer(model="cheap"), _generator(model="good")
    s.score("p", "t", "d")
    gen.generate(cv_text="cv", profile_text="p", vacancy_context="v")

    assert s._client.chat.completions.calls[0]["model"] == "cheap"
    assert gen._client.chat.completions.calls[0]["model"] == "good"


def test_role_classification_uses_the_model_it_was_given():
    """Классификация идёт на КАЖДЫЙ лид, поэтому модель обязана быть дешёвой."""
    c = _classifier(model="gpt-5.4-nano")
    c.classify("Backend Engineer. Go, Gin, PostgreSQL.")

    (kw,) = c._client.chat.completions.calls
    assert kw["model"] == "gpt-5.4-nano"


def test_role_classification_caps_the_reply_length():
    c = _classifier(max_output_tokens=800)
    c.classify("Backend Engineer. Go, Gin, PostgreSQL.")

    (kw,) = c._client.chat.completions.calls
    assert kw["max_completion_tokens"] == 800


# --- output cap -------------------------------------------------------------

def test_scoring_caps_the_reply_length():
    s = _scorer(max_output_tokens=500)
    s.score("профиль", "title", "описание")

    (kw,) = s._client.chat.completions.calls
    assert kw["max_completion_tokens"] == 500


def test_writing_caps_the_reply_length():
    gen = _generator(max_output_tokens=1500)
    gen.generate(cv_text="cv", profile_text="p", vacancy_context="v")

    (kw,) = gen._client.chat.completions.calls
    assert kw["max_completion_tokens"] == 1500


def test_hh_answers_cap_the_reply_length():
    gen = _generator(content='{"1": {"text": "да"}}', max_output_tokens=800)
    gen.answer_questions(
        cv_text="cv", profile_text="p", vacancy_context="v",
        questions=[{"id": "1", "type": "text", "prompt": "Опыт с C#?"}],
    )

    (kw,) = gen._client.chat.completions.calls
    assert kw["max_completion_tokens"] == 800


def test_hh_answers_still_request_json():
    """The cap must not displace the response_format the parser depends on."""
    gen = _generator(content='{"1": {"text": "да"}}')
    gen.answer_questions(
        cv_text="cv", profile_text="p", vacancy_context="v",
        questions=[{"id": "1", "type": "text", "prompt": "Опыт?"}],
    )

    (kw,) = gen._client.chat.completions.calls
    assert kw["response_format"] == {"type": "json_object"}


def test_role_classification_still_requests_json():
    """Разбор ответа ищет JSON: без response_format парсер молча съедет на fullstack."""
    c = _classifier()
    c.classify("Backend Engineer. Go, Gin, PostgreSQL.")

    (kw,) = c._client.chat.completions.calls
    assert kw["response_format"] == {"type": "json_object"}


# --- defaults ---------------------------------------------------------------

def test_generator_is_capped_even_when_the_caller_omits_the_kwarg():
    """test_send.py and older call sites construct this positionally."""
    gen = OpenAIMessageGenerator("key-unused", "some-model")
    assert gen._max_output_tokens > 0


def test_scorer_is_capped_even_when_the_caller_omits_the_kwarg():
    s = OpenAIRelevanceScorer("key-unused", "some-model")
    assert s._max_output_tokens > 0


def test_role_classifier_is_capped_even_when_the_caller_omits_the_kwarg():
    c = OpenAIRoleClassifier("key-unused", "some-model")
    assert c._max_output_tokens > 0