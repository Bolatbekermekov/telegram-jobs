"""Outreach channel port: the single interface every platform adapter implements."""
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class ChannelError(Exception):
    """A send failed for a reason specific to one lead (bad target, transport error)."""


class RateLimitedError(ChannelError):
    """The platform throttled/blocked us. The caller should stop THIS platform."""


class InvitePendingError(ChannelError):
    """Not a failure: the outreach was a LinkedIn connection request carrying the
    cover letter as its note (used when the person isn't a 1st-degree contact and
    can't be messaged for free). That invite is the complete outreach — no CV, and
    no CV chase after they accept. The caller records it as a normal send."""


class InviteWithoutNoteError(ChannelError):
    """Not a failure: a connection request went out with NO note, because the
    monthly personalized-invite quota is spent. The cover letter was not delivered,
    so this is not a send — the lead waits as `invited` until the person accepts,
    and a later run messages them properly."""


class ManualApplyRequired(ChannelError):
    """Not a hard failure: the application can't be completed automatically (CAPTCHA,
    login/registration wall, or an unrecognised form). The lead is flagged for a
    manual apply, with the URL, rather than counted as sent or failed."""


class ChannelUnavailable(ChannelError):
    """Not a hard failure: the channel can't be started right now for a transient
    setup reason (e.g. the CDP Chrome for Wellfound isn't running). The caller
    leaves this platform's leads `new` to retry next run — not counted as failed."""


@dataclass
class OutreachContent:
    body: str
    subject: str | None = None        # used by channels with needs_subject (email)
    attachment_path: str | None = None
    # Короткий самостоятельный текст для записки к запросу на контакт в LinkedIn.
    # У записки жёсткий предел площадки (LinkedInChannel.note_limit), которого у
    # письма нет, поэтому её пишут отдельно, а не отрезают от письма. Для всех
    # остальных каналов поле пустое, и они его не читают.
    note: str = ""


@runtime_checkable
class OutreachChannel(Protocol):
    name: str                  # one of: telegram | linkedin | hh | email | wellfound
    body_limit: int | None     # предел ДЛИНЫ ПИСЬМА; None = без предела
    needs_subject: bool        # True => a subject must be generated (email)

    def start(self) -> None: ...
    def stop(self) -> None: ...
    def send(self, target: str, content: OutreachContent) -> None: ...
