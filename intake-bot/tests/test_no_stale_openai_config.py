"""Ни один модуль не должен брать ключ и модель из config.OPENAI_*.

Эти имена ушли, когда появился выбор провайдера: они означали «всегда OpenAI».
Место сборки клиента, которое их использует, переключатель провайдера
проигнорирует — а поймать это иначе нечем, композиционный корень (api/webhook.py)
юнит-тестами не покрыт.
"""
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
# Только имена, несущие личность провайдера. OPENAI_MAX_OUTPUT_TOKENS — это
# просто потолок ответа, он одинаков для любого провайдера и имя сохранил.
_STALE = re.compile(r"config\.OPENAI_(?:API_KEY|MODEL_CHEAP|MODEL)\b")


def _sources():
    for path in _ROOT.rglob("*.py"):
        if ".venv" in path.parts or "__pycache__" in path.parts:
            continue
        if path.name == Path(__file__).name:
            continue
        yield path


def test_nothing_reads_the_old_openai_config_names():
    offenders = {}
    for path in _sources():
        hits = _STALE.findall(path.read_text(encoding="utf-8"))
        if hits:
            offenders[str(path.relative_to(_ROOT))] = sorted(set(hits))
    assert not offenders, f"используют старые имена вместо config.LLM_*: {offenders}"
