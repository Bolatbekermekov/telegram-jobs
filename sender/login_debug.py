"""Diagnose Telegram login: does the code request leave, and HOW did Telegram
send the code (App / SMS / Call)? Also lets you resend via the next method (SMS).

Run from the project root:
    sender/.venv/Scripts/python.exe sender/login_debug.py

It prints Telethon DEBUG logs (you can see the request go out and the reply come
back) plus the delivery type Telegram chose. On success it saves the same
userbot.session that `make test` / `make run` use, so you won't log in again.

NOTE: logs may contain your phone and the login code. Do NOT paste raw logs in
public chats. Share only the "РЕЗУЛЬТАТ ЗАПРОСА КОДА" block if you need help.
"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

from telethon import TelegramClient, functions  # noqa: E402
from telethon.errors import (  # noqa: E402
    FloodWaitError,
    PhoneNumberBannedError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)

from app import config  # noqa: E402


async def main() -> None:
    raw = input("Phone (with country code, e.g. +77775791341): ").strip()
    phone = raw.replace(" ", "").replace("-", "")

    client = TelegramClient(
        config.SESSION_PATH, config.TELEGRAM_API_ID, config.TELEGRAM_API_HASH
    )
    await client.connect()
    print("connected:", client.is_connected())
    print("dc / server:", client.session.dc_id, client.session.server_address)

    if await client.is_user_authorized():
        print("Уже авторизован — сессия есть, повторный логин не нужен.")
        await client.disconnect()
        return

    try:
        sent = await client.send_code_request(phone)
    except FloodWaitError as exc:
        print(f"\nFLOOD WAIT: Telegram просит подождать {exc.seconds} сек "
              f"(~{exc.seconds // 60} мин) перед новым запросом кода. Это и есть причина.")
        await client.disconnect()
        return
    except PhoneNumberInvalidError:
        print("\nНомер недействителен для Telegram. Проверь формат и код страны.")
        await client.disconnect()
        return
    except PhoneNumberBannedError:
        print("\nЭтот номер забанен в Telegram.")
        await client.disconnect()
        return

    print("\n=== РЕЗУЛЬТАТ ЗАПРОСА КОДА ===")
    print("delivery type :", type(sent.type).__name__)
    print("next type     :", type(sent.next_type).__name__ if sent.next_type else None)
    print("timeout (sec) :", sent.timeout)
    print("code length   :", getattr(sent.type, "length", None))
    print("=============================")
    print("SentCodeTypeApp  -> код ушёл В ПРИЛОЖЕНИЕ Telegram (чат 'Telegram'/777000), не SMS.")
    print("SentCodeTypeSms  -> код придёт по SMS.")
    print("SentCodeTypeCall -> позвонят и продиктуют код.\n")

    ans = input("Переслать код другим способом (next type, обычно SMS)? y/N: ").strip().lower()
    if ans == "y":
        try:
            sent = await client(
                functions.auth.ResendCodeRequest(phone, sent.phone_code_hash)
            )
            print("Resent. Новый delivery type:", type(sent.type).__name__)
        except FloodWaitError as exc:
            print(f"FLOOD WAIT при resend: подожди {exc.seconds} сек.")
            await client.disconnect()
            return

    code = input("\nВведи код (Enter — выйти без входа): ").strip()
    if not code:
        await client.disconnect()
        return

    try:
        await client.sign_in(phone, code)
    except SessionPasswordNeededError:
        pw = input("Включена 2FA. Введи пароль: ").strip()
        await client.sign_in(password=pw)
    except Exception as exc:  # noqa: BLE001
        print("sign_in error:", type(exc).__name__, exc)
        await client.disconnect()
        return

    me = await client.get_me()
    print(f"\n✅ Вход выполнен как {me.first_name} (@{me.username}). "
          f"Сессия: {config.SESSION_PATH}.session")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
