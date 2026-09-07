"""Какой LLM-провайдер обслуживает эту половину проекта.

NVIDIA NIM говорит на протоколе OpenAI, поэтому разница между провайдерами
сводится к трём значениям: ключ, базовый адрес и имена моделей. Всё остальное —
тот же клиент `openai` и те же вызовы.

Функция чистая и принимает env словарём (как platform_enabled в app/config.py):
провайдера можно проверить в тестах, не поднимая конфиг целиком — он на импорте
требует CV, подпись и телеграм-ключи.
"""
from dataclasses import dataclass
from typing import Mapping

OPENAI = "openai"
NVIDIA = "nvidia"
PROVIDERS = (OPENAI, NVIDIA)

NVIDIA_DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
# Замер 2026-09-07: из 81 модели каталога ключу доступно 13, и русский
# системный промпт держат только minimax-m3 и kimi-k3. У kimi разброс времени
# 16–52 с, поэтому по умолчанию — minimax (7.4 с на той же задаче).
NVIDIA_DEFAULT_MODEL = "minimaxai/minimax-m3"


@dataclass(frozen=True)
class LLMSettings:
    api_key: str
    # None, а не строка: пустая строка сломала бы клиент, а None означает
    # «адрес по умолчанию у SDK».
    base_url: str | None
    model: str
    model_cheap: str


def _require(env: Mapping[str, str], name: str, provider: str) -> str:
    value = (env.get(name) or "").strip()
    if not value:
        raise ValueError(
            f"Провайдер '{provider}' выбран, но {name} в .env пуст. "
            f"Заполни {name} или смени провайдера."
        )
    return value


def resolve(provider: str, env: Mapping[str, str]) -> LLMSettings:
    name = (provider or "").strip().lower()
    if name == OPENAI:
        return LLMSettings(
            api_key=_require(env, "OPENAI_API_KEY", OPENAI),
            base_url=None,
            model=env.get("OPENAI_MODEL") or "gpt-5.4-mini",
            model_cheap=env.get("OPENAI_MODEL_CHEAP") or "gpt-5.4-nano",
        )
    if name == NVIDIA:
        return LLMSettings(
            api_key=_require(env, "NVIDIA_API_KEY", NVIDIA),
            base_url=env.get("NVIDIA_BASE_URL") or NVIDIA_DEFAULT_BASE_URL,
            model=env.get("NVIDIA_MODEL") or NVIDIA_DEFAULT_MODEL,
            model_cheap=env.get("NVIDIA_MODEL_CHEAP") or NVIDIA_DEFAULT_MODEL,
        )
    raise ValueError(
        f"Неизвестный LLM-провайдер '{provider}'. Допустимые: {', '.join(PROVIDERS)}."
    )
