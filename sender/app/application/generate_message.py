"""Use-case: generate a personalized outreach message for a lead."""
from app.domain.lead import Lead


class GenerateMessage:
    def __init__(self, ai, cv_text: str, profile_text: str, signature_text: str = ""):
        # ai: object with .generate(cv_text, profile_text, vacancy_context) -> str
        self._ai = ai
        self._cv_text = cv_text
        self._profile_text = profile_text
        self._signature_text = signature_text.strip()

    def execute(self, lead: Lead) -> str:
        body = self._ai.generate(
            cv_text=self._cv_text,
            profile_text=self._profile_text,
            vacancy_context=lead.vacancy_context or lead.raw_text,
        )
        if self._signature_text:
            return f"{body}\n\n{self._signature_text}"
        return body


def subject_for(vacancy_context: str) -> str:
    """A short email subject derived from the vacancy text (first non-empty line)."""
    for line in vacancy_context.splitlines():
        line = line.strip()
        if line:
            return line[:120]
    return "Заявка на вакансию"
