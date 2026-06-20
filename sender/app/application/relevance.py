"""Score a vacancy's fit to the user's search profile (0-100) + a short reason."""
import json
import re
from typing import Protocol

_SCORE_SYSTEM = (
    "Ты оцениваешь, насколько вакансия подходит кандидату по его профилю поиска. "
    "Верни ТОЛЬКО JSON: {\"score\": <целое 0-100>, \"reason\": \"<кратко, до 120 символов>\"}. "
    "score = соответствие ролям, уровню и стеку из профиля. Будь строгим: "
    "не та роль или уровень выше Junior+ — низкий балл."
)


class RelevanceScorer(Protocol):
    def score(self, profile: str, title: str, description: str) -> tuple[int, str]:
        ...


def build_score_prompt(profile: str, title: str, description: str) -> tuple[str, str]:
    user = (
        f"=== ПРОФИЛЬ ПОИСКА ===\n{profile}\n\n"
        f"=== ВАКАНСИЯ ===\nНазвание: {title}\n\n{description}\n\n"
        "Верни только JSON."
    )
    return _SCORE_SYSTEM, user


def parse_score_response(raw: str) -> tuple[int, str]:
    try:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        data = json.loads(m.group(0)) if m else {}
        score = max(0, min(100, int(data.get("score", 0))))
        return score, str(data.get("reason", "")).strip()
    except Exception:  # noqa: BLE001 — malformed model output → drop the job
        return 0, ""
