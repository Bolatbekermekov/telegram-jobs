"""OpenAI-backed relevance scorer: one chat call → (score, reason)."""
from openai import OpenAI

from app.infrastructure.rate_limit import with_rate_limit_retry

from app.application.relevance import build_score_prompt, parse_score_response


class OpenAIRelevanceScorer:
    """Scores one job against the search profile. Runs on every job found, so it
    is the project's highest-volume OpenAI call — hence the cheap model."""

    def __init__(self, api_key: str, model: str, max_output_tokens: int = 2000,
                 base_url: str | None = None):
        self._client = OpenAI(api_key=api_key, base_url=base_url)
        self._model = model
        self._max_output_tokens = max_output_tokens

    def score(self, profile: str, title: str, description: str,
              location: str = "") -> tuple[int, str]:
        system, user = build_score_prompt(profile, title, description, location)
        resp = with_rate_limit_retry(lambda: self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_completion_tokens=self._max_output_tokens,
        ))
        return parse_score_response(resp.choices[0].message.content or "")
