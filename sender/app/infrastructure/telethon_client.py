"""Telethon userbot messenger: sends DMs from the user's own Telegram account."""
import re

from telethon import TelegramClient

_CAPTION_LIMIT = 1024


def _normalize(nickname: str) -> str:
    """Turn '@nick', 'nick', 'https://t.me/nick', 't.me/nick' into a username/entity ref."""
    n = nickname.strip()
    m = re.search(r"(?:t\.me/|telegram\.me/)(@?[\w\d_]+)", n, flags=re.IGNORECASE)
    if m:
        n = m.group(1)
    return n.lstrip("@")


class TelethonMessenger:
    def __init__(self, session_path: str, api_id: int, api_hash: str):
        self._client = TelegramClient(session_path, api_id, api_hash)

    def start(self) -> None:
        # First run prompts for phone number + login code in the console.
        self._client.start()

    def stop(self) -> None:
        self._client.disconnect()

    def send(self, nickname: str, text: str, attachment_path: str | None) -> None:
        username = _normalize(nickname)
        self._client.loop.run_until_complete(self._send(username, text, attachment_path))

    async def _send(self, username: str, text: str, attachment_path: str | None) -> None:
        entity = await self._client.get_entity(username)
        if attachment_path:
            if len(text) <= _CAPTION_LIMIT:
                await self._client.send_file(entity, attachment_path, caption=text)
            else:
                await self._client.send_message(entity, text)
                await self._client.send_file(entity, attachment_path)
        else:
            await self._client.send_message(entity, text)
