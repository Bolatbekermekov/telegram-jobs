"""OpenAI-backed summarizer: condenses a vacancy message into a short summary.

Contact detection is NOT done here (see app.domain.contact); this only produces
the vacancy_context text. Any failure returns "" so the lead is never lost.
"""
import json

from openai import OpenAI

_SYSTEM = (
    "Ты кратко суммируешь сообщения с вакансиями. Верни строго JSON "
    '{"vacancy_context": "..."} — роль, формат работы, условия и зарплата '
    "(если есть). Не добавляй контактов и ссылок, только суть вакансии."
)


class OpenAISummarizer:
    def __init__(self, api_key: str, model: str, client=None):
        self._client = client or OpenAI(api_key=api_key)
        self._model = model

    def summarize(self, raw_text: str) -> str:
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": raw_text},
                ],
            )
            data = json.loads(resp.choices[0].message.content)
            return (data.get("vacancy_context") or "").strip()
        except Exception:  # noqa: BLE001 — summarization is best-effort
            return ""
