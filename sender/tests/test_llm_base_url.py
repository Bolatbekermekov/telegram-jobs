"""Каждый клиент должен уметь смотреть не только в api.openai.com.

NVIDIA NIM — тот же протокол по другому адресу, поэтому единственное, что
нужно классам, — прокинуть base_url в SDK. Проверяем именно адрес собранного
клиента: подменять сам вызов бесполезно, ошибка «забыли прокинуть» живёт
ровно в конструкторе.
"""
import pytest

from app.infrastructure.openai_client import OpenAIMessageGenerator
from app.infrastructure.openai_contact import OpenAIContactDetector
from app.infrastructure.openai_relevance import OpenAIRelevanceScorer
from app.infrastructure.openai_role import OpenAIRoleClassifier

NIM = "https://integrate.api.nvidia.com/v1"
CLASSES = [OpenAIMessageGenerator, OpenAIContactDetector,
           OpenAIRelevanceScorer, OpenAIRoleClassifier]


@pytest.mark.parametrize("cls", CLASSES, ids=lambda c: c.__name__)
def test_base_url_reaches_the_sdk_client(cls):
    obj = cls("nvapi-test", "minimaxai/minimax-m3", base_url=NIM)
    assert str(obj._client.base_url).rstrip("/") == NIM


@pytest.mark.parametrize("cls", CLASSES, ids=lambda c: c.__name__)
def test_without_base_url_the_client_still_points_at_openai(cls):
    obj = cls("sk-test", "gpt-5.4-nano")
    assert "openai.com" in str(obj._client.base_url)
