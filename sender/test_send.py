"""One-off TEST: generate an outreach message for a lead and send it to a test
recipient (yourself), WITHOUT changing the lead's status in the sheet.

Use it to verify the prompt + CV attachment before the real run.

From the sender folder:
    python test_send.py --dry-run                  # only generate + print, no Telegram
    python test_send.py --to @your_username        # send the test to yourself
    python test_send.py --to @your_username --id 1 # pick a specific lead id
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app import config  # noqa: E402
from app.application.generate_message import GenerateMessage  # noqa: E402
from app.infrastructure.cv_loader import load_cv_text, load_text_file  # noqa: E402
from app.infrastructure.openai_client import OpenAIMessageGenerator  # noqa: E402
from app.infrastructure.sheets_repo import SheetsRepo  # noqa: E402
from app.infrastructure.telethon_client import TelethonMessenger  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--to", default=None, help="test recipient @username (required to send)")
    parser.add_argument("--id", default=None, help="lead id to use (default: first 'new')")
    parser.add_argument("--dry-run", action="store_true", help="generate only, do not send")
    args = parser.parse_args()

    cv_text = load_cv_text(config.CV_PATH)
    profile_text = load_text_file(config.PROFILE_PATH)
    repo = SheetsRepo(config.GOOGLE_SERVICE_ACCOUNT_FILE, config.SHEET_ID, config.SHEET_TAB)

    leads = repo.fetch_new_leads()
    if not leads:
        print("Нет лидов со статусом 'new'. Добавь вакансию через бота или расшарь таблицу на сервис-аккаунт.")
        return
    if args.id:
        leads = [lead for lead in leads if lead.lead_id == str(args.id)] or leads[:1]
    lead = leads[0]

    print(f"Лид #{lead.lead_id}  ->  {lead.nickname}")
    print(f"Вакансия: {lead.vacancy_context or lead.raw_text}\n")

    generator = GenerateMessage(
        OpenAIMessageGenerator(config.OPENAI_API_KEY, config.OPENAI_MODEL),
        cv_text,
        profile_text,
    )
    message = generator.execute(lead)
    print("--- СГЕНЕРИРОВАННОЕ СООБЩЕНИЕ ---")
    print(message)
    print("---------------------------------\n")

    if args.dry_run:
        print("dry-run: ничего не отправлено.")
        return

    if not args.to:
        print("Укажи получателя: --to @your_username  (или --dry-run, чтобы только показать текст).")
        return

    print(f"Отправляю ТЕСТ на {args.to} (CV приложу: {config.ATTACH_CV})...")
    print("При первом запуске Telegram попросит номер телефона и код из приложения.")
    messenger = TelethonMessenger(
        config.SESSION_PATH, config.TELEGRAM_API_ID, config.TELEGRAM_API_HASH
    )
    messenger.start()
    try:
        attachment = config.CV_PATH if config.ATTACH_CV else None
        messenger.send(args.to, message, attachment)
        print("✅ Тест отправлен. Проверь Telegram.")
    finally:
        messenger.stop()
    print("Статус лида в таблице НЕ менялся (это тест).")


if __name__ == "__main__":
    main()
