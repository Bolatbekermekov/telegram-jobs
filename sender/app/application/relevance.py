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


def score_and_filter(candidates, describe, scorer, profile, threshold, max_jobs):
    """Score up to `max_jobs` candidates; keep score >= threshold, stamp Summary.

    `describe(candidate) -> str` fetches the job description. A failing describe or
    score skips just that job. Returns the kept candidates (mutated with Summary).
    """
    kept = []
    for c in candidates[:max_jobs]:
        try:
            description = describe(c)
            score, reason = scorer.score(profile, c.title, description)
        except Exception:  # noqa: BLE001 — one bad job never kills the run
            continue
        if score >= threshold:
            c.summary = f"{score}/100: {reason}" if reason else f"{score}/100"
            kept.append(c)
    return kept
