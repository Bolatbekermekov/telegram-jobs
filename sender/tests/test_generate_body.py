"""A generation failure must not abort the whole send run.

Row 82 crashed the entire `make run` when OpenAI was briefly unreachable
(APIConnectionError during message generation), leaving 25 leads unprocessed.
generate_body() turns that into a per-lead skip instead of a crash.
"""
from app.application.generate_message import generate_body


class _Ok:
    def execute(self, lead):
        return "Здравствуйте! Заинтересовала ваша вакансия."


class _Boom:
    def __init__(self, exc):
        self._exc = exc

    def execute(self, lead):
        raise self._exc


def test_returns_body_and_no_error_on_success():
    body, err = generate_body(_Ok(), object())
    assert body == "Здравствуйте! Заинтересовала ваша вакансия."
    assert err is None


def test_swallows_a_connection_error():
    """The exact shape that crashed row 82 — a network/OpenAI outage."""
    boom = ConnectionError("nodename nor servname provided")
    body, err = generate_body(_Boom(boom), object())
    assert body is None
    assert err is boom


def test_swallows_any_generation_error():
    boom = RuntimeError("quota exhausted")
    body, err = generate_body(_Boom(boom), object())
    assert body is None
    assert err is boom


def test_does_not_swallow_keyboard_interrupt():
    """Ctrl-C must still stop the run — only real errors are absorbed."""
    import pytest
    with pytest.raises(KeyboardInterrupt):
        generate_body(_Boom(KeyboardInterrupt()), object())
