"""Use-case: detect contact + summarize a raw vacancy message, then save a lead."""
from app.domain.lead import ExtractedLead

_FALLBACK_LEN = 280


class ExtractLeadFromText:
    def __init__(self, detector, summarizer, repo):
        # detector: callable(text) -> Contact | None
        # summarizer: object with .summarize(text) -> str
        # repo: object with .append_lead(ExtractedLead) -> int (row id)
        self._detect = detector
        self._summarizer = summarizer
        self._repo = repo

    def execute(self, raw_text: str) -> ExtractedLead:
        contact = self._detect(raw_text)
        if contact is None:
            raise ValueError("no_contact")
        summary = self._summarizer.summarize(raw_text)
        if not summary:
            summary = raw_text.strip()[:_FALLBACK_LEN]
        lead = ExtractedLead(
            platform=contact.platform,
            target=contact.target,
            vacancy_context=summary,
            raw_text=raw_text,
        )
        self._repo.append_lead(lead)
        return lead
