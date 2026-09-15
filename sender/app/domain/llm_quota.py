"""Квота модели, которая не вернётся за минуту: сутки или баланс ключа.

Живьём 2026-09-15: бесплатный Gemini израсходовал дневные 500 запросов
gemini-3.5-flash-lite, но в отказе написал «Please retry in 24.96s» — ровно как
при поминутном лимите. `with_rate_limit_retry` ждал названное, и поиск простоял
ночь на LinkedIn, по три ожидания на каждую из 169 вакансий. Сутки от минуты
отличает только `quotaId` в деталях ответа: `GenerateRequestsPerDayPerProjectPerModel`
против `…PerMinute…`.

У OpenAI то же самое называется `insufficient_quota`: кончился баланс ключа, и
через минуту он не пополнится.
"""
import re

_PER_DAY_RE = re.compile(r"PerDay")
_BALANCE_RE = re.compile(r"insufficient_quota")
# Из текста отказа Gemini: «limit: 500, model: gemini-3.5-flash-lite».
_MODEL_RE = re.compile(r"model:\s*([\w.\-]+)")
_LIMIT_RE = re.compile(r"limit:\s*(\d+)")


class LLMQuotaExhausted(Exception):
    """Провайдер отказал по квоте, которую внутри прогона не переждать."""


def exhausted_quota_note(text: str) -> str | None:
    """Что кончилось — словами для человека; None, если это обычный поминутный лимит."""
    text = text or ""
    if _PER_DAY_RE.search(text):
        model = _MODEL_RE.search(text)
        limit = _LIMIT_RE.search(text)
        what = f"дневная квота {model.group(1)}" if model else "дневная квота модели"
        size = f" ({limit.group(1)} запросов в сутки)" if limit else ""
        return f"{what}{size} исчерпана"
    if _BALANCE_RE.search(text):
        return "у ключа модели кончился баланс (insufficient_quota)"
    return None
