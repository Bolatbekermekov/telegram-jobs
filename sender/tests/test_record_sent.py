"""What happens when the sheet write fails on a message that is already sent.

Lead #148: the Telegram message was delivered, `mark_sent` met a Sheets 502, and
the traceback ended the run with the row still `new` — so the next run would have
messaged the same person a second time. The write is retried now, but retries can
still be exhausted, and this is what must happen then.
"""
from app.domain.lead import STATUS_SENT
from app.interface.cli import _record_sent


class _Lead:
    lead_id = "148"
    row = 149
    target = "@Maha_zhuss"


class _OkRepo:
    def __init__(self):
        self.calls = []

    def mark_sent(self, lead, body, status):
        self.calls.append((lead, body, status))


class _BrokenRepo:
    def mark_sent(self, lead, body, status):
        raise RuntimeError("APIError: [-1]: <!DOCTYPE html> 502")


def test_a_successful_write_reports_true():
    repo = _OkRepo()
    assert _record_sent(repo, _Lead(), "тело", "telegram") is True
    (_, body, status), = repo.calls
    assert (body, status) == ("тело", STATUS_SENT)


def test_a_failed_write_does_not_raise():
    """Raising here is what killed the run and left the lead `new`."""
    assert _record_sent(_BrokenRepo(), _Lead(), "тело", "telegram") is False


def test_a_failed_write_names_the_row_and_the_duplicate_risk(capsys):
    _record_sent(_BrokenRepo(), _Lead(), "тело", "telegram")
    out = capsys.readouterr().out

    assert "#148" in out
    assert "@Maha_zhuss" in out
    assert "149" in out                      # the row to fix by hand
    assert STATUS_SENT in out
    assert "повторно" in out                 # says why it matters
