"""OpenAI-backed relevance scorer: one chat call → (score, reason)."""
from openai import BadRequestError

from app.infrastructure.openai_sdk import build_openai_client
from app.infrastructure.rate_limit import with_rate_limit_retry

from app.application.relevance import build_score_prompt, parse_score_response

# Оценка обязана быть воспроизводимой: по ней режется порог. Без явной
# температуры модель работала на 1.0, и одиннадцать побайтно одинаковых копий
# одного объявления получили в одном прогоне от 74 до 88 (замер 2026-08-28).
SCORE_TEMPERATURE = 0


class OpenAIRelevanceScorer:
    """Scores one job against the search profile. Runs on every job found, so it
    is the project's highest-volume OpenAI call — hence the cheap model."""

    # Сбрасывается в False на объекте, если модель отвергла параметр
    # (рассуждающие модели OpenAI принимают только значение по умолчанию), —
    # чтобы не платить отказом за каждую вакансию. На классе, а не только в
    # __init__: тесты и заглушки собирают скорер через __new__.
    _send_temperature = True

    def __init__(self, api_key: str, model: str, max_output_tokens: int = 2000,
                 base_url: str | None = None):
        self._client = build_openai_client(api_key, base_url)
        self._model = model
        self._max_output_tokens = max_output_tokens

    def _create(self, system: str, user: str):
        kwargs = dict(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_completion_tokens=self._max_output_tokens,
        )
        if self._send_temperature:
            kwargs["temperature"] = SCORE_TEMPERATURE
        return self._client.chat.completions.create(**kwargs)

    def score(self, profile: str, title: str, description: str,
              location: str = "") -> tuple[int, str]:
        system, user = build_score_prompt(profile, title, description, location)
        try:
            resp = with_rate_limit_retry(lambda: self._create(system, user))
        except BadRequestError as exc:
            if not (self._send_temperature and "temperature" in str(exc).lower()):
                raise
            self._send_temperature = False
            resp = with_rate_limit_retry(lambda: self._create(system, user))
        return parse_score_response(resp.choices[0].message.content or "")
