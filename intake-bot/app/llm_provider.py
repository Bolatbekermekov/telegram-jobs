"""Какой LLM-провайдер обслуживает эту половину проекта.

NVIDIA NIM и Gemini говорят на протоколе OpenAI, поэтому разница между
провайдерами сводится к трём значениям: ключ, базовый адрес и имена моделей.
Всё остальное — тот же клиент `openai` и те же вызовы.

Функция чистая и принимает env словарём (как platform_enabled в sender/app/config.py):
провайдера можно проверить в тестах, не поднимая конфиг целиком — он на импорте
требует ключи провайдера и Google.
"""
from dataclasses import dataclass
from typing import Mapping

OPENAI = "openai"
NVIDIA = "nvidia"
GEMINI = "gemini"


@dataclass(frozen=True)
class LLMSettings:
    api_key: str
    # None, а не строка: пустая строка сломала бы клиент, а None означает
    # «адрес по умолчанию у SDK».
    base_url: str | None
    model: str
    model_cheap: str


@dataclass(frozen=True)
class _Spec:
    """Как читать провайдера из окружения. Префикс общий у всех переменных."""
    prefix: str
    base_url: str | None
    model: str
    model_cheap: str


_SPECS: dict[str, _Spec] = {
    # У OpenAI base_url не задаём: SDK подставит свой адрес сам.
    OPENAI: _Spec("OPENAI", None, "gpt-5.4-mini", "gpt-5.4-nano"),
    # Замер 2026-09-07: из 81 модели каталога ключу доступно 13, и русский
    # системный промпт держат только minimax-m3 и kimi-k3. У kimi разброс
    # 16–52 с, у minimax 7.4 с — отсюда выбор.
    NVIDIA: _Spec("NVIDIA", "https://integrate.api.nvidia.com/v1",
                  "minimaxai/minimax-m3", "minimaxai/minimax-m3"),
    # Оба тира flash-lite, и это вторая редакция выбора. Сначала пишущим стоял
    # flash: flash-lite вставлял русскую строку «Мой стек: …» в английское
    # письмо (3 из 3), flash — ни разу. Причина оказалась не в модели, а в
    # промпте: формат диктовал подпись дословно по-русски, а правило языка
    # требовало «без единого русского слова», и flash-lite честно считал
    # подпись частью формата. После правки language_rule (см. там) flash-lite
    # даёт 4 чистых письма из 4.
    # Дальше решает квота, и она решает жёстко: у flash 20 запросов в минуту, и
    # прогон 2026-09-07 на нём вставал — «Please retry in 52s» на каждом втором
    # лиде. У flash-lite ~15 в минуту в замере, но без такого потолка, и живой
    # прогон он держит. У NVIDIA для сравнения ~2.
    # Модели 2.5 не брать вовсе: новым ключам они отвечают 404.
    GEMINI: _Spec("GEMINI", "https://generativelanguage.googleapis.com/v1beta/openai",
                  "gemini-3.5-flash-lite", "gemini-3.5-flash-lite"),
}

PROVIDERS = tuple(_SPECS)


def resolve(provider: str, env: Mapping[str, str]) -> LLMSettings:
    name = (provider or "").strip().lower()
    spec = _SPECS.get(name)
    if spec is None:
        raise ValueError(
            f"Неизвестный LLM-провайдер '{provider}'. "
            f"Допустимые: {', '.join(PROVIDERS)}."
        )

    def _get(suffix: str, default: str | None) -> str | None:
        return (env.get(f"{spec.prefix}_{suffix}") or "").strip() or default

    api_key = _get("API_KEY", None)
    if not api_key:
        raise ValueError(
            f"Провайдер '{name}' выбран, но {spec.prefix}_API_KEY в .env пуст. "
            f"Заполни {spec.prefix}_API_KEY или смени провайдера."
        )
    return LLMSettings(
        api_key=api_key,
        base_url=_get("BASE_URL", spec.base_url),
        model=_get("MODEL", spec.model),
        model_cheap=_get("MODEL_CHEAP", spec.model_cheap),
    )
