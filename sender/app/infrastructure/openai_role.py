"""Определение роли вакансии дешёвой моделью. Строение как у openai_relevance.py.

Отличие одно и намеренное: здесь передаётся response_format=json_object, потому
что разбор ответа ищет JSON. Сосед его не передаёт и полагается на разбор прозой.
"""
from openai import OpenAI

from app.application.classify_role import build_role_prompt, parse_role_response


class OpenAIRoleClassifier:
    """Один короткий вызов на лид, поэтому модель дешёвая (OPENAI_MODEL_CHEAP).

    Идёт ДО генерации письма: текст выбранного CV попадает в промпт генерации,
    значит роль должна быть известна раньше.
    """

    def __init__(self, api_key: str, model: str, max_output_tokens: int = 2000):
        self._client = OpenAI(api_key=api_key)
        self._model = model
        self._max_output_tokens = max_output_tokens

    def classify(self, vacancy_context: str) -> str:
        system, user = build_role_prompt(vacancy_context)
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            max_completion_tokens=self._max_output_tokens,
        )
        return parse_role_response(resp.choices[0].message.content or "")
