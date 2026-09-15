"""Use-case: send one outreach message to a lead and report the result."""
from dataclasses import dataclass

from app.domain.channel import (
    InvitePendingError,
    InviteWithoutNoteError,
    ManualApplyRequired,
    OutreachChannel,
    OutreachContent,
    RateLimitedError,
)
from app.domain.lead import Lead
from app.domain.llm_quota import LLMQuotaExhausted


@dataclass
class SendResult:
    ok: bool
    error: str = ""
    rate_limited: bool = False
    invited: bool = False        # connection request + cover letter sent (no CV); a normal send
    manual: bool = False         # apply couldn't be automated (CAPTCHA/login/unknown form)
    invited_plain: bool = False  # connect request sent WITHOUT the letter (quota spent)
    # Модель, отвечающая на вопросы формы, упёрлась в квоту на сутки или баланс:
    # с лидом всё в порядке, он остаётся `new`, а прогон останавливается.
    quota_exhausted: bool = False


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
        except InviteWithoutNoteError as exc:
            return SendResult(ok=False, error=str(exc), invited_plain=True)
        except ManualApplyRequired as exc:
            return SendResult(ok=False, error=str(exc), manual=True)
        except LLMQuotaExhausted as exc:
            return SendResult(ok=False, error=str(exc), quota_exhausted=True)
        except Exception as exc:  # noqa: BLE001
            return SendResult(ok=False, error=str(exc))
