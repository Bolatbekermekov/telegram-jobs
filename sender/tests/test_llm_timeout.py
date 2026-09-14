"""Зависший вызов модели не должен держать прогон по десять минут.

Живьём 2026-09-14 (лид #1195): прогон встал на «Генерирую сообщение...», поток
висел в чтении TLS-сокета к Google, а SDK без явного срока ждёт ответа 600 с и
повторяет запрос ещё дважды — до получаса на один вызов. Проверяем срок
собранного клиента, как base_url в test_llm_base_url.py: ошибка «забыли
передать» живёт ровно в конструкторе.
"""
import pytest

from app.infrastructure.openai_client import OpenAIMessageGenerator
from app.infrastructure.openai_contact import OpenAIContactDetector
from app.infrastructure.openai_relevance import OpenAIRelevanceScorer
from app.infrastructure.openai_role import OpenAIRoleClassifier

CLASSES = [OpenAIMessageGenerator, OpenAIContactDetector,
           OpenAIRelevanceScorer, OpenAIRoleClassifier]


def _read_timeout(client):
    """Срок чтения ответа: SDK хранит его числом или объектом httpx.Timeout."""
    t = client.timeout
    return getattr(t, "read", t)


@pytest.mark.parametrize("cls", CLASSES, ids=lambda c: c.__name__)
def test_a_hung_model_call_gives_up_within_two_minutes(cls):
    obj = cls("sk-test", "gpt-5.4-nano")
    read = _read_timeout(obj._client)
    assert read is not None and read <= 120
