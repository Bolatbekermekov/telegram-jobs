"""OpenAI-backed message generator for outreach."""
from openai import OpenAI

_SYSTEM = (
    "Ты пишешь персональные сообщения для отклика на вакансию от лица кандидата. "
    "Следуй правилам позиционирования из PROFILE и фактам из CV. "
    "Не выдумывай факты, которых нет в CV. Верни ТОЛЬКО текст сообщения, без пояснений."
)


class OpenAIMessageGenerator:
    def __init__(self, api_key: str, model: str):
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def generate(self, cv_text: str, profile_text: str, vacancy_context: str) -> str:
        user = (
            f"=== PROFILE (правила позиционирования) ===\n{profile_text}\n\n"
            f"=== CV ===\n{cv_text}\n\n"
            f"=== ВАКАНСИЯ ===\n{vacancy_context}\n\n"
            "Напиши сообщение для HR по правилам выше."
        )
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content.strip()
