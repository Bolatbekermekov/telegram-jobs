"""OpenAI-backed relevance scorer: one chat call → (score, reason)."""
from openai import OpenAI

from app.application.relevance import build_score_prompt, parse_score_response


class OpenAIRelevanceScorer:
    def __init__(self, api_key: str, model: str):
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def score(self, profile: str, title: str, description: str) -> tuple[int, str]:
        system, user = build_score_prompt(profile, title, description)
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return parse_score_response(resp.choices[0].message.content or "")
