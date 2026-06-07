"""OpenAI-backed message generator for outreach."""
from openai import OpenAI

_SYSTEM = (
    "Ты пишешь персональное сообщение для отклика на вакансию ОТ ЛИЦА кандидата "
    "(практикующего software engineer уровня middle, который рассматривает и разработку, и QA). "
    "Строго следуй правилам позиционирования из PROFILE и опирайся только на факты из CV; "
    "ничего не выдумывай. Пиши как живой человек в личке Telegram: коротко, по делу, тепло, "
    "без канцелярита и шаблонных клише. Язык сообщения = язык вакансии. "
    "КРИТИЧЕСКОЕ правило стиля: НИКОГДА не используй тире — ни длинное «—», ни среднее «–». "
    "Вместо тире ставь запятую, точку или скобки. Обычный дефис допустим только внутри слов. "
    "Верни ТОЛЬКО текст сообщения, без пояснений и без подписи-приписки от тебя."
)


def _strip_dashes(text: str) -> str:
    """Safety net: remove em/en dashes even if the model slips one in."""
    for sep in (" — ", " – ", " —", "— ", " –", "– "):
        text = text.replace(sep, ", ")
    text = text.replace("—", ", ").replace("–", ", ")
    while ", ," in text:
        text = text.replace(", ,", ",")
    return text.replace("  ", " ").strip()


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
        return _strip_dashes((resp.choices[0].message.content or "").strip())
