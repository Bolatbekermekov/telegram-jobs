"""Use-case: turn a raw vacancy message into a structured lead, then store it."""
from app.domain.lead import ExtractedLead


class ExtractLeadFromText:
    def __init__(self, extractor, repo):
        # extractor: object with .extract(text) -> ExtractedLead
        # repo: object with .append_lead(ExtractedLead) -> int (row id)
        self._extractor = extractor
        self._repo = repo

    def execute(self, raw_text: str) -> ExtractedLead:
        lead = self._extractor.extract(raw_text)
        if not lead.is_valid():
            raise ValueError("no_nickname")
        self._repo.append_lead(lead)
        return lead
