"""Log in to Telegram by QR code, no SMS/app code needed.

Use this when the login code never arrives. You scan a QR shown in the terminal
from the Telegram app on your phone, and the session is created.

Run from the project root:
    sender/.venv/Scripts/python.exe sender/qr_login.py

On your phone: Telegram -> Settings -> Devices -> Link Desktop Device -> scan the
QR in this terminal. Requires that account to be logged in on your phone already.
On success it saves the same userbot.session that `make test` / `make run` use.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import qrcode  # noqa: E402
from telethon import TelegramClient  # noqa: E402
from telethon.errors import SessionPasswordNeededError  # noqa: E402

from app import config  # noqa: E402


def _show_qr(url: str) -> None:
    qr = qrcode.QRCode(border=2)
    qr.add_data(url)
    qr.make()
    qr.print_ascii(invert=True)
    print("\nОтсканируй QR: Telegram -> Настройки -> Устройства -> Подключить устройство.\n")


async def main() -> None:
    client = TelegramClient(
        config.SESSION_PATH, config.TELEGRAM_API_ID, config.TELEGRAM_API_HASH
    )
    await client.connect()

    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"Уже авторизован как {me.first_name} (@{me.username}). Логин не нужен.")
        await client.disconnect()
        return

    qr_login = await client.qr_login()
    _show_qr(qr_login.url)

    while True:
        try:
            await qr_login.wait(timeout=30)
            break
        except asyncio.TimeoutError:
            await qr_login.recreate()
            print("QR обновился (старый истёк), новый:\n")
            _show_qr(qr_login.url)
        except SessionPasswordNeededError:
            pw = input("Включена 2FA. Введи пароль: ").strip()
            await client.sign_in(password=pw)
            break

    me = await client.get_me()
    print(f"\n✅ Вход выполнен как {me.first_name} (@{me.username}). "
          f"Сессия: {config.SESSION_PATH}.session")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
