"""Telegram channel: sends DMs from the user's own account via Telethon."""
import re

from telethon import TelegramClient

from app.domain.channel import OutreachContent

_CAPTION_LIMIT = 1024


def normalize_target(target: str) -> str:
    """'@nick', 'nick', 'https://t.me/nick', 't.me/nick' -> 'nick'."""
    n = target.strip()
    m = re.search(r"(?:t\.me/|telegram\.me/)(@?[\w\d_]+)", n, flags=re.IGNORECASE)
    if m:
        n = m.group(1)
    return n.lstrip("@")


class TelegramChannel:
    name = "telegram"
    body_limit = None
    needs_subject = False

    def __init__(self, session_path: str, api_id: int, api_hash: str):
        self._client = TelegramClient(session_path, api_id, api_hash)
        self._client.parse_mode = None  # raw text: don't mangle @usernames/URLs

    def start(self) -> None:
        self._client.start()

    def stop(self) -> None:
        self._client.disconnect()

    def send(self, target: str, content: OutreachContent) -> None:
        username = normalize_target(target)
        self._client.loop.run_until_complete(self._send(username, content))

    async def _send(self, username: str, content: OutreachContent) -> None:
        entity = await self._client.get_entity(username)
        attachment = content.attachment_path
        if attachment:
            if len(content.body) <= _CAPTION_LIMIT:
                await self._client.send_file(entity, attachment, caption=content.body)
            else:
                await self._client.send_message(entity, content.body)
                await self._client.send_file(entity, attachment)
        else:
            await self._client.send_message(entity, content.body)
