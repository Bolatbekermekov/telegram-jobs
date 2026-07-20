import pytest

from app.application.extract_lead import ExtractLeadFromText
from app.domain.contact import Contact


class _FakeSummarizer:
    def __init__(self, text): self._text = text
    def summarize(self, raw): return self._text


class _FakeRepo:
    def __init__(self): self.saved = []
    def append_lead(self, lead): self.saved.append(lead); return 1


def _detector(result):
    return lambda text: result


def test_saves_lead_with_detected_platform_and_target():
    repo = _FakeRepo()
    uc = ExtractLeadFromText(_detector(Contact("linkedin", "linkedin.com/in/x")),
                             _FakeSummarizer("Backend role"), repo)
    lead = uc.execute("some vacancy text linkedin.com/in/x")
    assert lead.platform == "linkedin"
    assert lead.target == "linkedin.com/in/x"
    assert lead.vacancy_context == "Backend role"
    assert repo.saved == [lead]


def test_raises_when_no_contact():
    repo = _FakeRepo()
    uc = ExtractLeadFromText(_detector(None), _FakeSummarizer("x"), repo)
    with pytest.raises(ValueError, match="no_contact"):
        uc.execute("no contact here")
    assert repo.saved == []


def test_falls_back_to_raw_text_when_summary_empty():
    repo = _FakeRepo()
    raw = "Длинный текст вакансии " * 20
    uc = ExtractLeadFromText(_detector(Contact("email", "a@b.com")),
                             _FakeSummarizer(""), repo)
    lead = uc.execute(raw)
    assert lead.vacancy_context == raw.strip()[:280]
    assert len(lead.vacancy_context) <= 280


# --- link-only messages fetch the vacancy -----------------------------------

from app.domain.contact import detect_contact      # noqa: E402


class _RecordingSummarizer:
    """Remembers what it was asked to summarise — that's the thing under test."""

    def __init__(self, text=""):
        self._text = text
        self.seen = None

    def summarize(self, raw):
        self.seen = raw
        return self._text


class _Fetcher:
    def __init__(self, text=""):
        self.text = text
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        return self.text


def test_link_only_message_summarises_the_fetched_vacancy():
    """Without this the summariser sees two URLs, answers that it can't open them,
    and that refusal becomes the «Вакансия» column and the cover letter."""
    raw = ("Vacancy: https://hh.kz/vacancy/135171273?from=share_ios\n\n"
           "Sent via hh mobile app https://hh.ru/mobile?from=share_ios")
    summarizer = _RecordingSummarizer("Специалист по внедрению ИИ, дата-центр")
    fetcher = _Fetcher("Специалист по внедрению ИИ. Мы — Tier IV дата-центр…")

    lead = ExtractLeadFromText(detect_contact, summarizer, _FakeRepo(),
                               fetcher).execute(raw)

    assert fetcher.calls == ["https://hh.ru/vacancy/135171273"]
    assert summarizer.seen == "Специалист по внедрению ИИ. Мы — Tier IV дата-центр…"
    assert lead.vacancy_context.startswith("Специалист по внедрению ИИ")
    assert lead.raw_text == raw          # the original message is still kept


def test_a_pasted_description_is_not_refetched():
    """No network call when the message already carries the vacancy."""
    raw = ("Ищем Middle QA Engineer в финтех. Обязанности: функциональное и "
           "регрессионное тестирование, тест-кейсы, баг-трекинг. Требования: опыт "
           "от 2 лет, REST API. Подробнее: https://hh.ru/vacancy/1")
    fetcher = _Fetcher("НЕ ДОЛЖНО ИСПОЛЬЗОВАТЬСЯ")
    summarizer = _RecordingSummarizer("ok")

    ExtractLeadFromText(detect_contact, summarizer, _FakeRepo(), fetcher).execute(raw)

    assert fetcher.calls == []
    assert summarizer.seen == raw


def test_a_failed_fetch_falls_back_to_the_message():
    """hh may throttle the datacenter IP — the lead must still be saved."""
    raw = "Vacancy: https://hh.ru/vacancy/135171273?from=share_ios"
    lead = ExtractLeadFromText(detect_contact, _RecordingSummarizer(""), _FakeRepo(),
                               _Fetcher("")).execute(raw)

    assert lead.platform == "hh"
    assert lead.vacancy_context               # falls back to the raw text


def test_the_use_case_still_works_without_a_fetcher():
    lead = ExtractLeadFromText(detect_contact, _RecordingSummarizer("s"),
                               _FakeRepo()).execute("Vacancy: https://hh.ru/vacancy/1")
    assert lead.vacancy_context == "s"

def test_linkedin_job_link_is_fetched_too():
    raw = "https://www.linkedin.com/jobs/view/4439324251/"
    summarizer = _RecordingSummarizer("Chatbot Developer в Mindrift")
    fetcher = _Fetcher("Chatbot Developer (WhatsApp, Telegram)\nКомпания: Mindrift\n…")

    ExtractLeadFromText(detect_contact, summarizer, _FakeRepo(), fetcher).execute(raw)

    assert fetcher.calls == ["https://www.linkedin.com/jobs/view/4439324251/"]
    assert summarizer.seen.startswith("Chatbot Developer")
