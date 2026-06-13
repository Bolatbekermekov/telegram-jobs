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
