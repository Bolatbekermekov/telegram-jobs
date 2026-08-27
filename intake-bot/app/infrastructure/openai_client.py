"""OpenAI-backed summarizer: condenses a vacancy message into a short summary.

Contact detection is NOT done here (see app.domain.contact); this only produces
the vacancy_context text. Any failure returns "" so the lead is never lost.
"""
import json

from openai import OpenAI

from app.domain.message_language import summary_language, summary_language_rule

_SYSTEM = (
    "Ты кратко суммируешь сообщения с вакансиями. Верни строго JSON "
    '{"vacancy_context": "..."} — роль, формат работы, условия и зарплата '
    "(если есть). Не добавляй контактов и ссылок, только суть вакансии."
)


class OpenAISummarizer:
    def __init__(self, api_key: str, model: str, client=None, max_output_tokens: int = 1000):
        self._client = client or OpenAI(api_key=api_key)
        self._model = model
        self._max_output_tokens = max_output_tokens

    def summarize(self, raw_text: str) -> str:
        try:
            # Язык пересказа называем прямо, а не надеемся, что модель сохранит
            # язык оригинала сама. Промпт выше целиком русский, и этого хватает,
            # чтобы переписать по-русски что угодно: в листе за 2026-08-26
            # русскую «Вакансию» получили все 35 строк с чисто английским
            # оригиналом. Дальше эта колонка идёт в письмо — лиду #441
            # (стажировка в Бангалоре) отклик так и ушёл, русским текстом через
            # Easy Apply. Считается язык внутри try по той же причине, что и всё
            # остальное здесь: лид дороже пересказа.
            system = _SYSTEM + summary_language_rule(summary_language(raw_text))
            resp = self._client.chat.completions.create(
                model=self._model,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": raw_text},
                ],
                max_completion_tokens=self._max_output_tokens,
            )
            data = json.loads(resp.choices[0].message.content)
            return (data.get("vacancy_context") or "").strip()
        except Exception:  # noqa: BLE001 — summarization is best-effort
            return ""
