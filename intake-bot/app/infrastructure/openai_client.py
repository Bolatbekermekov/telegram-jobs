"""OpenAI-backed extractor: pulls @nickname/url + vacancy summary from free text."""
import json

from openai import OpenAI

from app.domain.lead import ExtractedLead

_SYSTEM = (
    "Ты парсишь сообщения с вакансиями. Из текста извлеки:\n"
    "1) контакт получателя — Telegram @nickname или ссылка t.me/...;\n"
    "2) краткую суть вакансии (роль, формат работы, условия, зарплата если есть).\n"
    "Верни строго JSON: {\"nickname\": \"@...\", \"vacancy_context\": \"...\"}.\n"
    "Если контакта нет — nickname пустая строка. Нормализуй ник: всегда с @ или как t.me-ссылку."
)


class OpenAIExtractor:
    def __init__(self, api_key: str, model: str):
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def extract(self, raw_text: str) -> ExtractedLead:
        resp = self._client.chat.completions.create(
            model=self._model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": raw_text},
            ],
        )
        data = json.loads(resp.choices[0].message.content)
        return ExtractedLead(
            nickname=(data.get("nickname") or "").strip(),
            vacancy_context=(data.get("vacancy_context") or "").strip(),
            raw_text=raw_text,
        )
