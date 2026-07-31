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

        summary = self._vacancy_text(raw_text, contact.target)
        lead = ExtractedLead(
            platform=contact.platform,
            target=contact.target,
            vacancy_context=summary,
            raw_text=raw_text,
        )
        self._repo.append_lead(lead)
        return lead

    def _vacancy_text(self, raw_text: str, target: str) -> str:
        """The «Вакансия» column for this message — or "" when it can't be known.

        A phone share carries only a URL. The summariser can't open links, so it
        answers "не удалось извлечь содержание вакансии, пришлите текст", and that
        sentence lands in «Вакансия» and becomes the brief the cover letter is
        written from. Reading the page first is what prevents it.

        When the read comes back empty, return "" — do NOT fall through to
        summarising the bare URL. That fall-through is precisely how the refusal
        got stored anyway: the guard covered the path where the fetch worked and
        left the failing one alone, and rows 121 and 141 were saved with the
        model's apology as their vacancy text.

        Empty is honest and it is recoverable. This bot runs on a serverless
        function with an ~8s budget and a datacenter IP that LinkedIn and hh both
        throttle, so an empty read is far more often a moment's throttling than a
        dead link — the same LinkedIn post that failed for row 121 fetched fine
        later. The sender re-reads the link from the laptop before it generates
        anything (send_plan.needs_vacancy_refetch), which is where the second,
        unhurried attempt happens.
        """
        source_text = raw_text
        if self._fetch is not None and is_link_only(raw_text):
            fetched = self._fetch(target)
            if not fetched:
                return ""
            source_text = fetched

        summary = self._summarizer.summarize(source_text)
        if not summary:
            summary = source_text.strip()[:_FALLBACK_LEN]
        return summary
