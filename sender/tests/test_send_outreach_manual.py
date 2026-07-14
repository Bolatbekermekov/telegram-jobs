from app.application.send_outreach import SendOutreach
from app.domain.channel import ManualApplyRequired, OutreachContent


class _Lead:
    target = "https://job"


class _Chan:
    def send(self, target, content):
        raise ManualApplyRequired("gated: do it by hand")


def test_manual_apply_required_becomes_manual_result():
    res = SendOutreach(_Chan()).execute(_Lead(), OutreachContent(body="x"))
    assert res.ok is False
    assert res.manual is True
    assert "gated" in res.error
