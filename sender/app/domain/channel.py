"""Outreach channel port: the single interface every platform adapter implements."""
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class ChannelError(Exception):
    """A send failed for a reason specific to one lead (bad target, transport error)."""


class RateLimitedError(ChannelError):
    """The platform throttled/blocked us. The caller should stop THIS platform."""


@dataclass
class OutreachContent:
    body: str
    subject: str | None = None        # used by channels with needs_subject (email)
    attachment_path: str | None = None


@runtime_checkable
class OutreachChannel(Protocol):
    name: str                  # one of: telegram | linkedin | hh | email | wellfound
    body_limit: int | None     # max chars for body (LinkedIn note = 300); None = unlimited
    needs_subject: bool        # True => a subject must be generated (email)

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def send(self, target: str, content: OutreachContent) -> None: ...
