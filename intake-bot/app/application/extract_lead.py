"""Use-case: detect contact + summarize a raw vacancy message, then save a lead."""
from app.domain.lead import ExtractedLead
from app.domain.vacancy_text import is_link_only

_FALLBACK_LEN = 280


class ExtractLeadFromText:
    def __init__(self, detector, summarizer, repo, fetcher=None):
        # detector: callable(text) -> Contact | None
        # summarizer: object with .summarize(text) -> str
        # repo: object with .append_lead(ExtractedLead) -> int (row id)
        # fetcher: callable(url) -> str, the vacancy text behind a link ("" if
        #          unavailable). Optional so the use-case still runs offline.
        self._detect = detector
        self._summarizer = summarizer
        self._repo = repo
        self._fetch = fetcher

    def execute(self, raw_text: str) -> ExtractedLead:
        contact = self._detect(raw_text)
        if contact is None:
            raise ValueError("no_contact")

        # A phone share carries only a URL. The summariser can't open links — it
        # answers "не удалось извлечь детали вакансии", and that sentence becomes
        # the «Вакансия» column and then the basis of the cover letter. So when
        # there is no text to summarise, go and read the vacancy first.
        source_text = raw_text
        if self._fetch is not None and is_link_only(raw_text):
            fetched = self._fetch(contact.target)
            if fetched:
                source_text = fetched

        summary = self._summarizer.summarize(source_text)
        if not summary:
            summary = source_text.strip()[:_FALLBACK_LEN]
        lead = ExtractedLead(
            platform=contact.platform,
            target=contact.target,
            vacancy_context=summary,
            raw_text=raw_text,
        )
        self._repo.append_lead(lead)
        return lead
