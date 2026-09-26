"""Код подтверждения Greenhouse из Gmail владельца — по IMAP и только на чтение.

Решение владельца 2026-09-26: заявки Greenhouse с «enter the 8-character code to
confirm you're a human» доводить автоматически, а не отдавать в ручные (за два
дня таких набралось четыре: DoiT, Nakisa, Stripe, DoorDash India). Код приходит
на ту же почту, с которой бот шлёт письма (`SMTP_USER`), и её пароль приложения
Gmail открывает и IMAP — новых ключей и OAuth не нужно.

Ящик открывается readonly: письма не помечаются прочитанными и не трогаются.
Берётся самое новое письмо с кодом, пришедшее ПОСЛЕ нажатия «Отправить»: в
ящике лежат коды прошлых попыток к тем же компаниям, а код живёт недолго.
"""
import email
import imaplib
import time
from datetime import datetime, timedelta, timezone

from app.domain.security_code import extract_security_code

# Запас на расхождение часов нашей машины и почтового сервера.
_CLOCK_SLACK_S = 60


def _bodies(msg) -> str:
    parts = []
    for part in msg.walk():
        if part.get_content_type() in ("text/plain", "text/html"):
            payload = part.get_payload(decode=True) or b""
            parts.append(payload.decode(part.get_content_charset() or "utf-8", "replace"))
    return "\n".join(parts)


class GmailCodeReader:
    def __init__(self, user: str, password: str, host: str = "imap.gmail.com",
                 connect=None, now=time.time, sleep=time.sleep):
        self._user, self._password = user, password
        self._connect = connect or (lambda: imaplib.IMAP4_SSL(host, 993))
        self._now, self._sleep = now, sleep

    def _newest_code(self, since: float) -> str:
        box = self._connect()
        try:
            box.login(self._user, self._password)
            box.select("INBOX", readonly=True)
            day = (datetime.fromtimestamp(since, timezone.utc) - timedelta(days=1))
            typ, data = box.search(None, "FROM", '"greenhouse"', "SUBJECT", '"Security code"',
                                   "SINCE", day.strftime("%d-%b-%Y"))
            uids = (data[0] or b"").split() if data else []
            for uid in reversed(uids):           # новые — в конце выдачи
                typ, got = box.fetch(uid, "(INTERNALDATE BODY.PEEK[])")
                if typ != "OK" or not got or not isinstance(got[0], tuple):
                    continue
                arrived = imaplib.Internaldate2tuple(got[0][0])
                if arrived is None or time.mktime(arrived) < since - _CLOCK_SLACK_S:
                    continue
                code = extract_security_code(_bodies(email.message_from_bytes(got[0][1])))
                if code:
                    return code
            return ""
        finally:
            try:
                box.logout()
            except Exception:  # noqa: BLE001
                pass

    def code_since(self, since: float, timeout_s: float = 150, poll_s: float = 6) -> str:
        """Ждать письмо с кодом, пришедшее после `since`; "" — не дождались.

        Сбой ящика (пароль, сеть) — тоже "", а не исключение: заявка тогда уходит
        в ручные с понятной причиной, а не роняет прогон.
        """
        deadline = self._now() + timeout_s
        while True:
            try:
                code = self._newest_code(since)
            except Exception:  # noqa: BLE001 — ящик недоступен = кода нет
                code = ""
            if code or self._now() >= deadline:
                return code
            self._sleep(poll_s)
