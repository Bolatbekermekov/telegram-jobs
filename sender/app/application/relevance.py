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


def score_and_filter(candidates, describe, scorer, profile, threshold, max_jobs,
                     on_reject=None, scan_limit=None, on_scan_limit=None):
    """Скорить, пока не наберётся `max_jobs` ПРОШЕДШИХ порог вакансий.

    `max_jobs` считает попавших в лист, а не потраченные попытки. Раньше бюджет
    тратился на каждую оценку, и отвергнутые съедали его целиком: замер
    2026-08-22 на полном поиске — hh оценил 30, отверг 25, в таблицу попало 5;
    LinkedIn оценил 30 и не пропустил ничего. Обе площадки упёрлись ровно в
    бюджет, и вакансии за отказниками не начинались.

    `describe(candidate) -> str` качает описание. Сбой describe или score
    пропускает эту вакансию, но слот сканирования тратит — иначе площадка, у
    которой отваливается каждое описание, крутила бы цикл по всему найденному.

    `scan_limit` — потолок на число оценок за прогон. Он обязателен по цене:
    одна оценка это скачанная страница плюс вызов модели (замерено ~19 с на
    LinkedIn и ~38 с на hh), поэтому площадка, где всё ниже порога, без потолка
    сканировала бы всё найденное часами. `None` снимает потолок.

    `on_scan_limit(scanned, kept)` зовётся ОДИН раз, когда цикл остановил именно
    потолок. Молчаливый обрез читается как «на площадке пусто», а это неправда:
    непросмотренное осталось, и само оно в следующий прогон не попадёт.

    `on_reject(candidate)` вызывается для вакансии, НЕ дотянувшей до порога, —
    чтобы её запомнили и больше не оценивали. Без этого отказник не сохранялся
    никуда: следующий прогон снова качал его описание и снова платил за скоринг,
    а поскольку порядок выдачи детерминированный, одни и те же отказники
    занимали весь бюджет, и вакансии за ними не начинались никогда.

    Вакансию, описание которой не прочиталось, в `on_reject` не отдаём: это сбой
    сети, а не вердикт о вакансии, и списывать её навсегда из-за таймаута нельзя.
    """
    kept = []
    scanned = 0
    for c in candidates:
        if len(kept) >= max_jobs:
            return kept
        if scan_limit is not None and scanned >= scan_limit:
            if on_scan_limit is not None:
                on_scan_limit(scanned, len(kept))
            return kept
        scanned += 1
        try:
            description = describe(c)
            score, reason = scorer.score(profile, c.title, description)
        except Exception:  # noqa: BLE001 — one bad job never kills the run
            continue
        if score >= threshold:
            c.summary = f"{score}/100: {reason}" if reason else f"{score}/100"
            kept.append(c)
        elif on_reject is not None:
            on_reject(c)
    return kept
