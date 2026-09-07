"""Лимит запросов в минуту не должен ронять прогон.

Бесплатные тиры (Gemini ~8–15 запросов в минуту, NVIDIA ~2) отвечают 429, когда
лиды идут подряд. А идут они подряд именно в плохие моменты: пауза
MIN/MAX_DELAY_SECONDS стоит ПОСЛЕ успешной отправки, поэтому серия падений
(например, hh не показал поле письма) прогоняет лиды вплотную. Прогон 2026-09-07
так и умер: три 429 подряд, и защита «LLM недоступен» остановила всё на седьмом
лиде из 81.

Ждать надо десятками секунд, а не миллисекундами: окно у квоты поминутное.
"""
import httpx
import pytest
from openai import RateLimitError

from app.infrastructure.rate_limit import with_rate_limit_retry


def _429(message="quota"):
    return RateLimitError(message, response=httpx.Response(
        429, request=httpx.Request("POST", "https://example.test")), body=None)


# Так выглядит настоящий отказ Gemini (замер 2026-09-07). Заголовка Retry-After
# у него нет — срок лежит только в тексте, поэтому его и разбираем.
GEMINI_429 = (
    "Error code: 429 - You exceeded your current quota. "
    "* Quota exceeded for metric: generate_content_free_tier_requests, "
    "limit: 20, model: gemini-3.5-flash\nPlease retry in 52.52279s")


def test_returns_value_without_sleeping_when_there_is_no_limit():
    slept = []
    assert with_rate_limit_retry(lambda: "ок", sleep=slept.append) == "ок"
    assert slept == []


def test_retries_after_429_and_returns_the_later_success():
    calls = []
    slept = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise _429()
        return "письмо"

    assert with_rate_limit_retry(flaky, sleep=slept.append) == "письмо"
    assert len(calls) == 3


def test_waits_long_enough_for_a_per_minute_window():
    # Короткий backoff здесь бесполезен: окно квоты поминутное, и повтор через
    # секунду просто потратит вторую попытку впустую.
    slept = []

    def always_limited():
        raise _429()

    with pytest.raises(RateLimitError):
        with_rate_limit_retry(always_limited, sleep=slept.append)
    assert slept, "не подождал ни разу"
    assert slept == sorted(slept), "паузы должны расти"
    assert sum(slept) >= 60, f"суммарно ждал {sum(slept)} с — минуту не переживём"


def test_gives_up_instead_of_hanging_forever():
    calls = []

    def always_limited():
        calls.append(1)
        raise _429()

    with pytest.raises(RateLimitError):
        with_rate_limit_retry(always_limited, sleep=lambda _: None)
    assert len(calls) <= 4, "слишком много попыток — прогон встанет надолго"


def test_other_errors_are_not_retried():
    # 429 это «подожди», а любая другая ошибка — повод отдать её наверх сразу:
    # прогон сам решит, считать ли её отказом.
    calls = []

    def boom():
        calls.append(1)
        raise ValueError("что-то другое")

    with pytest.raises(ValueError):
        with_rate_limit_retry(boom, sleep=lambda _: None)
    assert len(calls) == 1


# --- проводка: мало иметь хелпер, его должны звать настоящие классы ---

class _FakeCompletions:
    """Клиент, который отвечает 429 дважды, а на третий раз — нормальным ответом."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        if self.calls < 3:
            raise _429()
        return self.payload


class _Msg:
    def __init__(self, content): self.content = content


class _Choice:
    def __init__(self, content): self.message = _Msg(content)


class _Resp:
    def __init__(self, content): self.choices = [_Choice(content)]


def _fake_client(monkeypatch, obj, content):
    fake = _FakeCompletions(_Resp(content))
    monkeypatch.setattr(obj, "_client",
                        type("C", (), {"chat": type("Ch", (), {"completions": fake})()})())
    return fake


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    monkeypatch.setattr("app.infrastructure.rate_limit.time.sleep", lambda _: None)


def test_message_generator_survives_a_rate_limit():
    from app.infrastructure.openai_client import OpenAIMessageGenerator
    gen = OpenAIMessageGenerator("k", "m")
    import pytest as _p
    with _p.MonkeyPatch.context() as mp:
        fake = _fake_client(mp, gen, "Hello, this is the letter.")
        out = gen.generate("cv", "profile", "Junior Python Developer, remote")
    assert fake.calls == 3
    assert "letter" in out


def test_role_classifier_survives_a_rate_limit():
    # Классификатор роли зовётся на КАЖДЫЙ лид, наравне с генерацией письма,
    # то есть удваивает расход квоты в прогоне.
    from app.infrastructure.openai_role import OpenAIRoleClassifier
    clf = OpenAIRoleClassifier("k", "m")
    import pytest as _p
    with _p.MonkeyPatch.context() as mp:
        fake = _fake_client(mp, clf, "fullstack")
        clf.classify("Fullstack developer, React and Node")
    assert fake.calls == 3


def test_waits_exactly_as_long_as_the_server_asked():
    # Угадывать вредно в обе стороны: меньше — потратим попытку впустую,
    # больше — прогон стоит на ровном месте. Сервер называет срок сам.
    slept = []
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise _429(GEMINI_429)
        return "письмо"

    assert with_rate_limit_retry(flaky, sleep=slept.append) == "письмо"
    assert len(slept) == 1
    assert 52.5 <= slept[0] <= 60, f"ждал {slept[0]} с вместо названных 52.5"


def test_falls_back_to_the_ladder_when_no_delay_is_given():
    slept = []
    with pytest.raises(RateLimitError):
        with_rate_limit_retry(lambda: (_ for _ in ()).throw(_429()), sleep=slept.append)
    assert sum(slept) >= 60


def test_an_absurd_delay_is_capped():
    # Иначе один ответ «retry in 3600» останавливает прогон на час.
    slept = []
    err = "Please retry in 3600s"
    with pytest.raises(RateLimitError):
        with_rate_limit_retry(lambda: (_ for _ in ()).throw(_429(err)), sleep=slept.append)
    assert max(slept) <= 120, f"ждал {max(slept)} с — слишком долго"
