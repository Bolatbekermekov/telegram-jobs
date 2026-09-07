"""Клиенты бота должны уметь смотреть не только в api.openai.com.

NVIDIA NIM — тот же протокол по другому адресу, поэтому классам достаточно
прокинуть base_url в SDK. Проверяем адрес собранного клиента: ошибка «забыли
прокинуть» живёт ровно в конструкторе.
"""
import pytest

from app.infrastructure.openai_client import OpenAISummarizer
from app.infrastructure.openai_relevance import OpenAIRelevanceScorer

NIM = "https://integrate.api.nvidia.com/v1"
CLASSES = [OpenAISummarizer, OpenAIRelevanceScorer]


@pytest.mark.parametrize("cls", CLASSES, ids=lambda c: c.__name__)
def test_base_url_reaches_the_sdk_client(cls):
    obj = cls("nvapi-test", "minimaxai/minimax-m3", base_url=NIM)
    assert str(obj._client.base_url).rstrip("/") == NIM


@pytest.mark.parametrize("cls", CLASSES, ids=lambda c: c.__name__)
def test_without_base_url_the_client_still_points_at_openai(cls):
    obj = cls("sk-test", "gpt-5.4-nano")
    assert "openai.com" in str(obj._client.base_url)


@pytest.mark.parametrize("cls", CLASSES, ids=lambda c: c.__name__)
def test_injected_client_still_wins(cls):
    # Тесты бота подсовывают фейковый клиент; base_url не должен это ломать.
    sentinel = object()
    obj = cls("nvapi-test", "m", client=sentinel, base_url=NIM)
    assert obj._client is sentinel
