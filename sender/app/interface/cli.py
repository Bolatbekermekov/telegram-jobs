"""Interactive CLI: read `new` leads, generate, approve per lead, send, update sheet."""
import random
import time

from app import config
from app.application.generate_message import GenerateMessage
from app.application.send_outreach import SendOutreach
from app.domain.lead import STATUS_FAILED, STATUS_SENT, STATUS_SKIPPED
from app.infrastructure.cv_loader import load_cv_text, load_text_file
from app.infrastructure.openai_client import OpenAIMessageGenerator
from app.infrastructure.sheets_repo import SheetsRepo
from app.infrastructure.telethon_client import TelethonMessenger


def _prompt(msg: str) -> str:
    try:
        return input(msg).strip()
    except EOFError:
        return ""


def _edit_text(current: str) -> str:
    print("\nВведи новый текст. Пустая строка = закончить ввод:\n")
    lines: list[str] = []
    while True:
        line = _prompt("")
        if line == "":
            break
        lines.append(line)
    return "\n".join(lines) if lines else current


def run() -> None:
    print("== telegram-jobs sender ==")
    cv_text = load_cv_text(config.CV_PATH)
    profile_text = load_text_file(config.PROFILE_PATH)

    repo = SheetsRepo(config.GOOGLE_SERVICE_ACCOUNT_JSON, config.SHEET_ID, config.SHEET_TAB)
    generator = GenerateMessage(
        OpenAIMessageGenerator(config.OPENAI_API_KEY, config.OPENAI_MODEL),
        cv_text,
        profile_text,
    )
    messenger = TelethonMessenger(config.SESSION_PATH, config.TELEGRAM_API_ID, config.TELEGRAM_API_HASH)
    sender = SendOutreach(messenger, config.CV_PATH, config.ATTACH_CV)

    leads = repo.fetch_new_leads()
    if not leads:
        print("Нет новых лидов (статус 'new'). Выход.")
        return

    print(f"Найдено новых лидов: {len(leads)}. Дневной лимит: {config.DAILY_SEND_LIMIT}.")
    print("Подключаюсь к Telegram (при первом запуске спросит номер и код)...")
    messenger.start()

    sent_count = 0
    try:
        for lead in leads:
            if sent_count >= config.DAILY_SEND_LIMIT:
                print(f"\nДостигнут дневной лимит ({config.DAILY_SEND_LIMIT}). Останавливаюсь.")
                break

            print("\n" + "=" * 60)
            print(f"Лид #{lead.lead_id}  →  {lead.nickname}")
            print(f"Вакансия: {lead.vacancy_context or lead.raw_text}")
            print("-" * 60)
            print("Генерирую сообщение...")
            message = generator.execute(lead)

            while True:
                print("\n--- СООБЩЕНИЕ ---\n" + message + "\n-----------------")
                choice = _prompt("[s]end / [k]skip / [e]dit / [r]egenerate / [q]uit: ").lower()
                if choice in ("s", "send", ""):
                    result = sender.execute(lead, message)
                    if result.ok:
                        repo.mark_sent(lead, message, STATUS_SENT)
                        sent_count += 1
                        print(f"✅ Отправлено ({sent_count}/{config.DAILY_SEND_LIMIT}).")
                        if sent_count < config.DAILY_SEND_LIMIT and lead is not leads[-1]:
                            delay = random.randint(config.MIN_DELAY_SECONDS, config.MAX_DELAY_SECONDS)
                            print(f"⏳ Пауза {delay} c (анти-бан)...")
                            time.sleep(delay)
                    else:
                        repo.mark_status(lead, STATUS_FAILED)
                        print(f"❌ Ошибка отправки: {result.error}")
                    break
                if choice in ("k", "skip"):
                    repo.mark_status(lead, STATUS_SKIPPED)
                    print("⏭  Пропущено.")
                    break
                if choice in ("e", "edit"):
                    message = _edit_text(message)
                    continue
                if choice in ("r", "regenerate"):
                    print("Генерирую заново...")
                    message = generator.execute(lead)
                    continue
                if choice in ("q", "quit"):
                    print("Выход по запросу.")
                    return
                print("Не понял. Введи s / k / e / r / q.")
    finally:
        messenger.stop()
        print(f"\nГотово. Отправлено за сессию: {sent_count}.")


if __name__ == "__main__":
    run()
