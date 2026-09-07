"""Конфиг sender'а выбирает провайдера по SENDER_LLM_PROVIDER.

Отдельная переменная от бота нарочно: у Vercel лимит функции 10 секунд, у
ноутбука времени сколько угодно, поэтому половины должны переключаться
независимо.
"""
import importlib

import pytest

from app import config as config_module


@pytest.fixture
def reloaded(monkeypatch):
    """Перечитать конфиг с подменённым окружением и вернуть всё как было."""
    def _load(**env):
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        return importlib.reload(config_module)
    yield _load
    monkeypatch.undo()
    importlib.reload(config_module)


def test_default_provider_is_openai(reloaded):
    cfg = reloaded(SENDER_LLM_PROVIDER="")
    assert cfg.LLM_BASE_URL is None
    assert cfg.LLM_API_KEY.startswith("sk-")
    assert cfg.LLM_MODEL and cfg.LLM_MODEL_CHEAP


def test_nvidia_provider_switches_key_model_and_url(reloaded):
    cfg = reloaded(SENDER_LLM_PROVIDER="nvidia", NVIDIA_API_KEY="nvapi-test")
    assert cfg.LLM_BASE_URL == "https://integrate.api.nvidia.com/v1"
    assert cfg.LLM_API_KEY == "nvapi-test"
    assert cfg.LLM_MODEL == "minimaxai/minimax-m3"
    assert cfg.LLM_MODEL_CHEAP == "minimaxai/minimax-m3"


def test_nvidia_selected_without_key_fails_on_import(reloaded):
    with pytest.raises(ValueError) as e:
        reloaded(SENDER_LLM_PROVIDER="nvidia", NVIDIA_API_KEY="")
    assert "NVIDIA_API_KEY" in str(e.value)


def test_intake_switch_does_not_touch_the_sender(reloaded):
    # Переключение бота не должно уводить ноутбук на другого провайдера.
    cfg = reloaded(INTAKE_LLM_PROVIDER="nvidia", SENDER_LLM_PROVIDER="openai",
                   NVIDIA_API_KEY="nvapi-test")
    assert cfg.LLM_BASE_URL is None
