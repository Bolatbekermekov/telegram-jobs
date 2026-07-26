"""OpenAI-backed fallback contact detector: one chat call → the raw answer.

Deliberately on the writing model (OPENAI_MODEL), not the cheap one: this runs at
most once per Threads lead, leads are units per week, and the cost of getting it
wrong is a message to the wrong person. Vetting lives in
`application/contact_llm.py`; this only carries the call.
"""
from openai import OpenAI

from app.application.contact_llm import build_contact_prompt


class OpenAIContactDetector:
    """Callable as `detector(thread_text) -> str`, matching the `llm` hook of
    `resolve_threads_lead`. The answer is returned raw and unparsed on purpose —
    the caller vets it, and an empty string is a valid "nothing found"."""

    def __init__(self, api_key: str, model: str, max_output_tokens: int = 2000):
        self._client = OpenAI(api_key=api_key)
        self._model = model
        self._max_output_tokens = max_output_tokens

    def __call__(self, thread_text: str) -> str:
        system, user = build_contact_prompt(thread_text)
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_completion_tokens=self._max_output_tokens,
        )
        return resp.choices[0].message.content or ""
