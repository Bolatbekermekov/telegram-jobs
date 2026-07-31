"""The vacancy-reading modules are a deliberate copy of the intake bot's.

The two apps deploy separately — the intake bot to Vercel from `intake-bot/`,
the sender to this laptop — so a shared package at the repo root would not ship
with the serverless build. `app/domain/contact.py` is duplicated for the same
reason. What makes a copy safe is a mechanical check that it is still a copy:
byte-identity, not "looks similar".

Both files are environment-neutral by construction. `fetch_vacancy_text` takes
its timeout as an argument, so the sender's longer budget (no serverless clock)
is passed at the call site instead of forking a constant here.
"""
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_MIRRORED = [
    ("app/domain/vacancy_text.py", "intake-bot/app/domain/vacancy_text.py"),
    ("app/infrastructure/vacancy_fetcher.py",
     "intake-bot/app/infrastructure/vacancy_fetcher.py"),
]


@pytest.mark.parametrize("here,there", _MIRRORED)
def test_the_copy_is_still_byte_identical_to_the_intake_original(here, there):
    ours = _ROOT / "sender" / here
    theirs = _ROOT / there
    if not theirs.exists():
        pytest.skip("intake-bot/ absent — nothing to compare against")
    assert ours.read_bytes() == theirs.read_bytes(), (
        f"{here} has drifted from {there}. Edit one, copy it over the other; "
        "these two must not diverge silently."
    )
