"""Keeps at most one outreach channel open at a time.

Telethon (Telegram) and Playwright (LinkedIn/HH/Wellfound) cannot run in the
same process simultaneously, so while processing leads in id order we hold a
single open channel and switch lazily as the platform changes. A fresh channel
is built on every (re)open — stopped channels are never reused.
"""


class ChannelSwitcher:
    def __init__(self, build):
        """`build(platform) -> channel` returns a fresh, not-yet-started channel."""
        self._build = build
        self._channel = None
        self._platform = None

    def for_platform(self, platform):
        """Return a started channel for `platform`, switching if a different one
        is open. Reuses the open channel when the platform already matches."""
        if self._platform != platform:
            self.close()
            channel = self._build(platform)
            channel.start()                 # may raise -> switcher stays empty
            self._channel = channel
            self._platform = platform
        return self._channel

    def close(self):
        """Stop the open channel, if any. Never raises."""
        if self._channel is not None:
            try:
                self._channel.stop()
            except Exception:  # noqa: BLE001 — a broken stop must not abort the run
                pass
            self._channel = None
            self._platform = None
