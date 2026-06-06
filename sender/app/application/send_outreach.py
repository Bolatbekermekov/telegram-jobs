"""Use-case: send one outreach message to a lead and report the result."""
from dataclasses import dataclass

from app.domain.lead import Lead


@dataclass
class SendResult:
    ok: bool
    error: str = ""


class SendOutreach:
    def __init__(self, messenger, cv_path: str, attach_cv: bool):
        # messenger: object with .send(nickname, text, attachment_path|None) -> None
        self._messenger = messenger
        self._cv_path = cv_path
        self._attach_cv = attach_cv

    def execute(self, lead: Lead, text: str) -> SendResult:
        try:
            attachment = self._cv_path if self._attach_cv else None
            self._messenger.send(lead.nickname, text, attachment)
            return SendResult(ok=True)
        except Exception as exc:  # noqa: BLE001
            return SendResult(ok=False, error=str(exc))
