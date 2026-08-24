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
