"""Use-case: generate a personalized outreach message for a lead."""
from app.domain.lead import Lead


class GenerateMessage:
    def __init__(self, ai, cv_text: str, profile_text: str):
        # ai: object with .generate(cv_text, profile_text, vacancy_context) -> str
        self._ai = ai
        self._cv_text = cv_text
        self._profile_text = profile_text

    def execute(self, lead: Lead) -> str:
        return self._ai.generate(
            cv_text=self._cv_text,
            profile_text=self._profile_text,
            vacancy_context=lead.vacancy_context or lead.raw_text,
        )
