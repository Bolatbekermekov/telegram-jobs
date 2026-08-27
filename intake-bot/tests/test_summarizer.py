from app.infrastructure.openai_client import OpenAISummarizer


class _Msg:
    def __init__(self, content): self.message = type("M", (), {"content": content})


class _Resp:
    def __init__(self, content): self.choices = [_Msg(content)]


class _FakeClient:
    def __init__(self, content=None, raise_exc=None):
        self._content = content
        self._raise = raise_exc
        self.seen = None            # kwargs последнего вызова
        self.chat = type("C", (), {"completions": self})()

    def create(self, **kwargs):
        self.seen = kwargs
        if self._raise:
            raise self._raise
        return _Resp(self._content)

    @property
    def system_prompt(self):
        return self.seen["messages"][0]["content"]


def _summarize(text):
    """Прогнать текст через суммаризатор и вернуть системный промпт, который ушёл."""
    client = _FakeClient(content='{"vacancy_context": "ok"}')
    OpenAISummarizer("key", "model", client=client).summarize(text)
    return client.system_prompt


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


# --- язык пересказа --------------------------------------------------------
#
# Замер 2026-08-26: 35 английских оригиналов из 35 получили русскую «Вакансию».
# Дальше эта колонка идёт в письмо, и лиду #441 (стажировка в Бангалоре) отклик
# уже ушёл по-русски. Разбор самого правила — в tests/test_summary_language.py.

ENGLISH_POSTING = (
    "Senior Technology Product Manager. Booking.com is a global online travel "
    "platform that connects travelers with accommodations. You will own the "
    "roadmap for our partner-facing tooling. On-site in Amsterdam."
)
RUSSIAN_POSTING = (
    "Ищем Go-разработчика в продуктовую команду банка. Формат: удалённо из "
    "любой точки, оформление по ТК. Зарплата от 400 000 ₽. Стек: Go, "
    "PostgreSQL, Kafka. Писать в личку."
)


def test_english_posting_orders_an_english_summary():
    prompt = _summarize(ENGLISH_POSTING)
    assert "English" in prompt          # указание продублировано по-английски
    assert "ПО-АНГЛИЙСКИ" in prompt


def test_russian_posting_is_not_nudged_into_english():
    prompt = _summarize(RUSSIAN_POSTING)
    assert "English" not in prompt
    assert "по-русски" in prompt


def test_a_message_with_nothing_but_a_link_orders_no_language():
    """Языка не знаем — не называем никакого."""
    prompt = _summarize("https://www.linkedin.com/jobs/view/backend-engineer-4455783459")
    assert "English" not in prompt
    assert "ВАЖНО" not in prompt


def test_the_format_and_the_ban_on_contacts_survive_the_language_rule():
    """Правило языка ДОБАВЛЯЕТСЯ к промпту, а не заменяет его.

    `vacancy_context` читает не только человек: строгий JSON разбирается кодом,
    а контакт для отклика берётся из detect_contact по оригиналу, и ссылка,
    подсунутая в пересказ, увела бы отклик не туда.
    """
    for text in (ENGLISH_POSTING, RUSSIAN_POSTING, "https://hh.ru/vacancy/136486822"):
        prompt = _summarize(text)
        assert '{"vacancy_context": "..."}' in prompt
        assert "Не добавляй контактов и ссылок" in prompt


def test_the_response_is_still_requested_as_json():
    client = _FakeClient(content='{"vacancy_context": "ok"}')
    OpenAISummarizer("key", "model", client=client).summarize(ENGLISH_POSTING)
    assert client.seen["response_format"] == {"type": "json_object"}
