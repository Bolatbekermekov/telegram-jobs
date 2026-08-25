"""Оценка «подходит ли вакансия профилю»: один вызов модели -> (0-100, причина).

Интейковая копия `sender/app/infrastructure/openai_relevance.py`; почему копия,
а не общий пакет — в докстроке app/application/relevance.py.

Отличий от ноутбучной копии два, и оба про то, что здесь serverless-функция с
бюджетом ~10 секунд на всё сообщение, а не ноутбук, который может подождать:

* `max_retries=0`. По умолчанию SDK молча повторяет запрос дважды, и выставленный
  таймаут в 2,5 секунды превращается в 7,5 — то есть в убитую функцию. Убитая
  функция значит, что Telegram повторит вебхук, а повтор значит задвоенный лид:
  ровно та цена, ради которой append в sheets_repo намеренно не ретраится.
* таймаут на КАЖДЫЙ вызов, а не на клиент: сколько секунд осталось у сообщения,
  знает только вызывающая сторона (см. `_relevance_scorer` в api/webhook.py).

Ошибки наружу не глотаются: их ловит `ExtractLeadFromText._relevance`, потому
что решение «лид дороже оценки» принимается там и должно защищать любой
подставленный скорер, а не только этот.
"""
from openai import OpenAI

from app.application.relevance import build_score_prompt, parse_score_response

# Столько же, сколько у ноутбучной копии. JSON в ответе крошечный, но модели
# рассуждающие, и потолок считает вместе с рассуждением: срезать его значит
# получить обрыв на полуслове, который `parse_score_response` прочитает как
# «оценки нет».
_MAX_OUTPUT_TOKENS = 2000
# Столько ждём ответа, если вызывающая сторона не сказала иначе.
_TIMEOUT_SECONDS = 2.5


class OpenAIRelevanceScorer:
    """Одна вакансия -> (score, reason) | None. Модель — дешёвая: этот вызов
    добавляется к КАЖДОМУ пересланному сообщению, поверх уже живущей там
    суммаризации."""

    def __init__(self, api_key: str, model: str, client=None,
                 max_output_tokens: int = _MAX_OUTPUT_TOKENS):
        self._client = client or OpenAI(api_key=api_key, max_retries=0)
        self._model = model
        self._max_output_tokens = max_output_tokens

    def score(self, profile: str, title: str, description: str,
              timeout: float = _TIMEOUT_SECONDS) -> tuple[int, str] | None:
        system, user = build_score_prompt(profile, title, description)
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_completion_tokens=self._max_output_tokens,
            timeout=timeout,
        )
        return parse_score_response(resp.choices[0].message.content or "")
