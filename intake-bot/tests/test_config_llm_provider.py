"""Конфиг бота выбирает провайдера по INTAKE_LLM_PROVIDER.

Отдельно от ноутбука нарочно: у Vercel лимит функции 10 секунд, и облако должно
остаться на OpenAI, даже когда рассылка уже переехала на NVIDIA.
"""
import importlib

import pytest

from app import config as config_module


@pytest.fixture
def reloaded(monkeypatch):
    def _load(**env):
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        return importlib.reload(config_module)
    yield _load
    monkeypatch.undo()
    importlib.reload(config_module)


def test_default_provider_is_openai(reloaded):
    cfg = reloaded(INTAKE_LLM_PROVIDER="")
    assert cfg.LLM_BASE_URL is None
    assert cfg.LLM_API_KEY.startswith("sk-")


def test_bot_stays_on_the_cheap_tier(reloaded):
    # Суммаризация пересланной вакансии — извлечение, а не письмо: бот всегда
    # берёт дешёвый тир, как и до появления провайдеров.
    cfg = reloaded(INTAKE_LLM_PROVIDER="openai", OPENAI_MODEL_CHEAP="gpt-x-nano")
    assert cfg.LLM_MODEL == "gpt-x-nano"


def test_nvidia_provider_switches_key_model_and_url(reloaded):
    cfg = reloaded(INTAKE_LLM_PROVIDER="nvidia", NVIDIA_API_KEY="nvapi-test")
    assert cfg.LLM_BASE_URL == "https://integrate.api.nvidia.com/v1"
    assert cfg.LLM_API_KEY == "nvapi-test"
    assert cfg.LLM_MODEL == "minimaxai/minimax-m3"


def test_nvidia_selected_without_key_fails_on_import(reloaded):
    with pytest.raises(ValueError) as e:
        reloaded(INTAKE_LLM_PROVIDER="nvidia", NVIDIA_API_KEY="")
    assert "NVIDIA_API_KEY" in str(e.value)


def test_sender_switch_does_not_touch_the_bot(reloaded):
    cfg = reloaded(SENDER_LLM_PROVIDER="nvidia", INTAKE_LLM_PROVIDER="openai",
                   NVIDIA_API_KEY="nvapi-test")
    assert cfg.LLM_BASE_URL is None
