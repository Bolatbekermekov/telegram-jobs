"""Telegram channel: sends DMs from the user's own account via Telethon."""
import asyncio
import re

from telethon import TelegramClient

from app.domain.channel import ChannelUnavailable, OutreachContent, RateLimitedError

_CAPTION_LIMIT = 1024

# Telegram's anti-spam / flood limits, matched by message so detection survives
# Telethon class-hierarchy changes and wrapped errors:
#   PeerFloodError  -> "Too many requests (caused by SendMessageRequest)"
#   FloodWaitError  -> "A wait of N seconds is required (caused by ...)"
_FLOOD_MARKERS = ("too many requests", "peerflood", "flood", "a wait of")


def is_flood_error(exc: Exception) -> bool:
    """True when a Telegram send failed on a flood / spam-limit (transient, so the
    caller should stop this platform and retry, not hard-fail the lead)."""
    return any(m in str(exc).lower() for m in _FLOOD_MARKERS)


def _ensure_event_loop() -> None:
    """Give the thread an event loop before Telethon looks for one.

    Telethon resolves its loop through asyncio.get_event_loop() (helpers.py,
    get_running_loop). Up to Python 3.11 that created a loop on demand; 3.12
    deprecated it and 3.14 raises `There is no current event loop in thread
    'MainThread'` instead — so merely constructing TelegramClient fails outside a
    coroutine. qr_login.py never hit this because it runs inside asyncio.run();
    the send loop is synchronous, so it has to set the loop up itself.
    """
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())


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
        _ensure_event_loop()
        self._client = TelegramClient(session_path, api_id, api_hash)
        self._client.parse_mode = None  # raw text: don't mangle @usernames/URLs

    def start(self) -> None:
        # Connect and check authorisation ourselves instead of calling
        # client.start(): on a revoked or missing session that helper falls back to
        # `input('Please enter your phone')`, which hangs a terminal run waiting for
        # a number nobody is there to type. Same run_until_complete idiom as send().
        loop = self._client.loop
        loop.run_until_complete(self._client.connect())
        if not loop.run_until_complete(self._client.is_user_authorized()):
            raise ChannelUnavailable(
                "сессия Telegram недействительна (отозвана или не создана) — "
                "выполни `make login_telegram` и отсканируй QR заново")

    def stop(self) -> None:
        self._client.disconnect()

    def send(self, target: str, content: OutreachContent) -> None:
        username = normalize_target(target)
        try:
            self._client.loop.run_until_complete(self._send(username, content))
        except Exception as exc:  # noqa: BLE001
            # A spam/flood limit is transient — surface it as RateLimitedError so the
            # run loop stops Telegram and leaves its leads for the next run, instead
            # of burning them as `failed`. Other errors keep their normal handling.
            if is_flood_error(exc):
                raise RateLimitedError(
                    f"Telegram ограничил рассылку (спам-лимит): {exc}") from exc
            raise

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
