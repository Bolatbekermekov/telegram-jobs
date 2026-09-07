"""Выбор LLM-провайдера: OpenAI или NVIDIA NIM (OpenAI-совместимый endpoint).

Функция чистая и берёт env словарём — как platform_enabled в app/config.py,
чтобы провайдера можно было проверить, не поднимая весь конфиг с его CV,
подписью и телеграм-ключами.
"""
import pytest

from app.llm_provider import resolve


def test_openai_leaves_base_url_unset():
    # None, а не строка: SDK сам подставит свой адрес. Пустая строка сломала бы
    # клиент, поэтому проверяем именно None.
    s = resolve("openai", {"OPENAI_API_KEY": "sk-test"})
    assert s.base_url is None
    assert s.api_key == "sk-test"


def test_openai_reads_its_own_models():
    s = resolve("openai", {
        "OPENAI_API_KEY": "sk-test",
        "OPENAI_MODEL": "gpt-x",
        "OPENAI_MODEL_CHEAP": "gpt-x-nano",
    })
    assert s.model == "gpt-x"
    assert s.model_cheap == "gpt-x-nano"


def test_openai_models_default_to_the_current_tiers():
    s = resolve("openai", {"OPENAI_API_KEY": "sk-test"})
    assert s.model == "gpt-5.4-mini"
    assert s.model_cheap == "gpt-5.4-nano"


def test_nvidia_points_at_nim_and_minimax():
    s = resolve("nvidia", {"NVIDIA_API_KEY": "nvapi-test"})
    assert s.api_key == "nvapi-test"
    assert s.base_url == "https://integrate.api.nvidia.com/v1"
    # Единственная доступная на ключе модель, которая держит русский ответ.
    assert s.model == "minimaxai/minimax-m3"
    assert s.model_cheap == "minimaxai/minimax-m3"


def test_nvidia_base_url_and_models_are_overridable():
    s = resolve("nvidia", {
        "NVIDIA_API_KEY": "nvapi-test",
        "NVIDIA_BASE_URL": "https://example.test/v1",
        "NVIDIA_MODEL": "moonshotai/kimi-k3",
        "NVIDIA_MODEL_CHEAP": "nvidia/nemotron-3-super-120b-a12b",
    })
    assert s.base_url == "https://example.test/v1"
    assert s.model == "moonshotai/kimi-k3"
    assert s.model_cheap == "nvidia/nemotron-3-super-120b-a12b"


def test_openai_key_of_the_other_provider_is_not_used():
    # Ключи не взаимозаменяемы: nvapi-… в api.openai.com даёт 401. Молча взять
    # чужой ключ хуже, чем упасть на старте.
    with pytest.raises(ValueError) as e:
        resolve("openai", {"NVIDIA_API_KEY": "nvapi-test"})
    assert "OPENAI_API_KEY" in str(e.value)


def test_nvidia_without_its_key_names_the_variable_to_fill():
    with pytest.raises(ValueError) as e:
        resolve("nvidia", {"OPENAI_API_KEY": "sk-test"})
    assert "NVIDIA_API_KEY" in str(e.value)


def test_blank_key_counts_as_missing():
    with pytest.raises(ValueError):
        resolve("nvidia", {"NVIDIA_API_KEY": "   "})


def test_unknown_provider_lists_the_valid_ones():
    with pytest.raises(ValueError) as e:
        resolve("anthropic", {"OPENAI_API_KEY": "sk-test"})
    msg = str(e.value)
    assert "anthropic" in msg
    for known in ("openai", "nvidia", "gemini"):
        assert known in msg


def test_provider_name_is_trimmed_and_case_insensitive():
    # .env правят руками; " NVIDIA " не должно означать «неизвестный провайдер».
    s = resolve("  NVIDIA  ", {"NVIDIA_API_KEY": "nvapi-test"})
    assert s.base_url == "https://integrate.api.nvidia.com/v1"

def test_gemini_points_at_the_openai_compatible_endpoint():
    # У Gemini есть endpoint, говорящий на протоколе OpenAI, поэтому провайдер
    # добавляется теми же тремя значениями, что и NVIDIA.
    s = resolve("gemini", {"GEMINI_API_KEY": "AIza-test"})
    assert s.api_key == "AIza-test"
    assert s.base_url == "https://generativelanguage.googleapis.com/v1beta/openai"
    # Тиры здесь расходятся, в отличие от NVIDIA, и по замеру 2026-09-07.
    # Пишущий: flash-lite в трёх письмах из трёх вставил русскую строку («Мой
    # стек: …») в английское письмо, flash — ни разу. Письмо читает человек.
    assert s.model == "gemini-3.5-flash"
    # Массовый: flash упирается в 429 на девятом запросе, flash-lite держит ~15
    # в минуту. Боту нужно два вызова подряд на каждое сообщение.
    assert s.model_cheap == "gemini-3.5-flash-lite"


def test_gemini_base_url_and_models_are_overridable():
    s = resolve("gemini", {
        "GEMINI_API_KEY": "AIza-test",
        "GEMINI_BASE_URL": "https://example.test/v1",
        "GEMINI_MODEL": "gemini-3.5-flash",
        "GEMINI_MODEL_CHEAP": "gemini-3.1-flash-lite",
    })
    assert s.base_url == "https://example.test/v1"
    assert s.model == "gemini-3.5-flash"
    assert s.model_cheap == "gemini-3.1-flash-lite"


def test_gemini_without_its_key_names_the_variable_to_fill():
    with pytest.raises(ValueError) as e:
        resolve("gemini", {"OPENAI_API_KEY": "sk-test", "NVIDIA_API_KEY": "nvapi-test"})
    assert "GEMINI_API_KEY" in str(e.value)
