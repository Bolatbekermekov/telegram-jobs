"""Оракул «человек или канал»: важна не сетевая часть, а трактовка ответов."""
import json
import urllib.error
import io

import pytest

from app.infrastructure import telegram_chat as tc


@pytest.fixture(autouse=True)
def clear_cache():
    tc._cache.clear()
    yield
    tc._cache.clear()


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return io.BytesIO(json.dumps(self._payload).encode())

    def __exit__(self, *exc):
        return False


def _answering(payload, calls=None):
    def fake(url, timeout=None):
        if calls is not None:
            calls.append(url)
        return _Resp(payload)
    return fake


def test_channel_is_refused(monkeypatch):
    monkeypatch.setattr(tc.urllib.request, "urlopen",
                        _answering({"ok": True, "result": {"type": "channel"}}))
    assert tc.is_writable_telegram_target("@devs_it", "TOKEN") is False


def test_supergroup_is_refused(monkeypatch):
    monkeypatch.setattr(tc.urllib.request, "urlopen",
                        _answering({"ok": True, "result": {"type": "supergroup"}}))
    assert tc.is_writable_telegram_target("@some_chat", "TOKEN") is False


def test_private_is_allowed(monkeypatch):
    monkeypatch.setattr(tc.urllib.request, "urlopen",
                        _answering({"ok": True, "result": {"type": "private"}}))
    assert tc.is_writable_telegram_target("@Adapty_Talent_Bot", "TOKEN") is True


def test_chat_not_found_is_unknown(monkeypatch):
    def raising(url, timeout=None):
        raise urllib.error.HTTPError(url, 400, "Bad Request", {}, None)
    monkeypatch.setattr(tc.urllib.request, "urlopen", raising)
    assert tc.is_writable_telegram_target("@ivan_hr", "TOKEN") is None


def test_network_failure_is_unknown(monkeypatch):
    def raising(url, timeout=None):
        raise OSError("timed out")
    monkeypatch.setattr(tc.urllib.request, "urlopen", raising)
    assert tc.is_writable_telegram_target("@ivan_hr", "TOKEN") is None


def test_tme_link_is_asked_by_username(monkeypatch):
    calls = []
    monkeypatch.setattr(tc.urllib.request, "urlopen",
                        _answering({"ok": True, "result": {"type": "channel"}}, calls))
    assert tc.is_writable_telegram_target("https://t.me/devs_it/", "TOKEN") is False
    assert "chat_id=%40devs_it" in calls[0]


def test_repeat_question_costs_no_request(monkeypatch):
    calls = []
    monkeypatch.setattr(tc.urllib.request, "urlopen",
                        _answering({"ok": True, "result": {"type": "channel"}}, calls))
    tc.is_writable_telegram_target("@devs_it", "TOKEN")
    tc.is_writable_telegram_target("https://t.me/devs_it", "TOKEN")
    assert len(calls) == 1


def test_invite_link_is_never_asked(monkeypatch):
    def forbidden(url, timeout=None):
        raise AssertionError("приглашение — не ник, запрос не нужен")
    monkeypatch.setattr(tc.urllib.request, "urlopen", forbidden)
    assert tc.is_writable_telegram_target("https://t.me/+AbCdEf", "TOKEN") is None


def test_no_token_means_no_question(monkeypatch):
    def forbidden(url, timeout=None):
        raise AssertionError("без токена спрашивать нечем")
    monkeypatch.setattr(tc.urllib.request, "urlopen", forbidden)
    assert tc.is_writable_telegram_target("@devs_it", "") is None


# --- бюджет на одно сообщение ------------------------------------------------
# Правило спрашивает про КАЖДОГО кандидата, а дайджест умеет перечислить десяток
# ников подряд. На serverless-функции с ~10 секундами это смертельно: Telegram
# повторит вебхук по таймауту, и лид задвоится. Поэтому у вебхука общий бюджет на
# сообщение, а исчерпанный бюджет отвечает «не знаю» — то есть в пользу лида.

import api.webhook as wh


def test_budget_stops_the_questions(monkeypatch):
    clock = [1000.0]
    asked = []
    monkeypatch.setattr(wh.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(wh, "is_writable_telegram_target",
                        lambda t, token, timeout=None: asked.append(t) or False)

    ask = wh._telegram_oracle()
    assert ask("@a") is False
    clock[0] += wh._ORACLE_BUDGET_SECONDS + 0.1
    assert ask("@b") is None
    assert asked == ["@a"]


def test_each_message_gets_a_fresh_budget(monkeypatch):
    clock = [1000.0]
    asked = []
    monkeypatch.setattr(wh.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(wh, "is_writable_telegram_target",
                        lambda t, token, timeout=None: asked.append(t) or False)

    wh._telegram_oracle()("@a")
    clock[0] += 60
    wh._telegram_oracle()("@b")
    assert asked == ["@a", "@b"]


def test_the_last_question_may_not_outlive_the_budget(monkeypatch):
    """Таймаут последнего запроса урезается остатком, а не берётся полным."""
    clock = [1000.0]
    seen = []
    monkeypatch.setattr(wh.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(wh, "is_writable_telegram_target",
                        lambda t, token, timeout=None: seen.append(timeout))

    ask = wh._telegram_oracle()
    clock[0] += wh._ORACLE_BUDGET_SECONDS - 0.5
    ask("@a")
    assert seen == [pytest.approx(0.5)]


def test_the_whole_message_shares_one_budget(monkeypatch):
    """Текст сообщения, текст поста и развёрнутые ссылки — один разбор, один
    бюджет. Иначе три секунды превращаются в двенадцать, то есть в таймаут."""
    clock = [1000.0]
    asked = []
    monkeypatch.setattr(wh.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(wh, "is_writable_telegram_target",
                        lambda t, token, timeout=None: asked.append(t) or False)

    detect = wh._detector(wh._telegram_oracle())
    detect("пиши @ivan_hr")
    clock[0] += wh._ORACLE_BUDGET_SECONDS + 0.1
    detect("а лучше @maria_hr")
    assert asked == ["@ivan_hr"]
