"""Adapt one generated body to a channel's limits and subject requirement."""
from app.domain.channel import OutreachContent


def _truncate(body: str, limit: int) -> str:
    if len(body) <= limit:
        return body
    window = body[:limit]
    cut = window.rfind(" ")
    if cut > 0:
        return window[:cut].rstrip()
    return window


def format_for_channel(channel, body: str, subject: str | None,
                       attachment_path: str | None) -> OutreachContent:
    out_body = body
    if channel.body_limit is not None:
        out_body = _truncate(body, channel.body_limit)
    out_subject = subject if channel.needs_subject else None
    return OutreachContent(body=out_body, subject=out_subject,
                           attachment_path=attachment_path)
