"""Use-case: send one outreach message to a lead and report the result."""
from dataclasses import dataclass

from app.domain.channel import (
    InvitePendingError,
    ManualApplyRequired,
    OutreachChannel,
    OutreachContent,
    RateLimitedError,
)
from app.domain.lead import Lead


@dataclass
class SendResult:
    ok: bool
    error: str = ""
    rate_limited: bool = False
    invited: bool = False        # connection request + cover letter sent (no CV); a normal send
    manual: bool = False         # apply couldn't be automated (CAPTCHA/login/unknown form)


class SendOutreach:
    def __init__(self, channel: OutreachChannel):
        self._channel = channel

    def execute(self, lead: Lead, content: OutreachContent) -> SendResult:
        try:
            self._channel.send(lead.target, content)
            return SendResult(ok=True)
        except RateLimitedError as exc:
            return SendResult(ok=False, error=str(exc), rate_limited=True)
        except InvitePendingError as exc:
            return SendResult(ok=False, error=str(exc), invited=True)
        except ManualApplyRequired as exc:
            return SendResult(ok=False, error=str(exc), manual=True)
        except Exception as exc:  # noqa: BLE001
            return SendResult(ok=False, error=str(exc))
