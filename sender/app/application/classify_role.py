"""Какая роль у вакансии. Решает модель, потому что слова решают плохо.

Регулярка по ключевым словам на 101 отправленном письме не смогла определить
роль в 9 случаях: объявление вида «ищем инженера, который соберёт пайплайны с
моделями и не боится бэкенда» не содержит ни `AI`, ни `backend` в узнаваемом
виде. Поэтому выбор идёт по смыслу требований.
"""
import json
import re
from typing import Protocol

from app.domain.cv_role import DEFAULT_ROLE, ROLE_DESCRIPTIONS, normalize_role

_ROLE_LINES = "\n".join(f"- {role}: {desc}"
                        for role, desc in ROLE_DESCRIPTIONS.items())

_ROLE_SYSTEM = (
    "Ты определяешь, к какой роли относится вакансия. "
    'Верни ТОЛЬКО JSON: {"role": "<один ключ из списка ниже>"}. '
    "Выбирай ПО СМЫСЛУ задач и требований, а не по совпадению слов в заголовке. "
    "Если вакансия про несколько направлений сразу или роль не ясна, верни "
    f'"{DEFAULT_ROLE}". Ключи ролей:\n{_ROLE_LINES}'
)


class RoleClassifier(Protocol):
    def classify(self, vacancy_context: str) -> str:
        ...


def build_role_prompt(vacancy_context: str) -> tuple[str, str]:
    user = f"=== ВАКАНСИЯ ===\n{vacancy_context}\n\nВерни только JSON."
    return _ROLE_SYSTEM, user


def parse_role_response(raw: str) -> str:
    """Ответ модели -> валидная роль. Любой мусор становится DEFAULT_ROLE."""
    try:
        m = re.search(r"\{.*\}", raw or "", re.DOTALL)
        data = json.loads(m.group(0)) if m else {}
        return normalize_role(data.get("role"))
    except Exception:  # noqa: BLE001 — чужой текст, разбор может не удаться
        return DEFAULT_ROLE


def classify_role(classifier, vacancy_context: str) -> str:
    """Роль лида. Никогда не бросает: без роли лид всё равно должен уехать.

    Ошибки проглатываются по той же причине, что и в `generate_body`: обвал
    OpenAI не должен уносить весь прогон. Лид получит запасное CV, то есть
    ровно то, которое уходит сегодня.
    """
    if not (vacancy_context or "").strip():
        return DEFAULT_ROLE
    try:
        return normalize_role(classifier.classify(vacancy_context))
    except Exception:  # noqa: BLE001 — сбой классификации это не потеря лида
        return DEFAULT_ROLE
