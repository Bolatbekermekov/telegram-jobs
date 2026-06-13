"""Interactive CLI: read `new` leads, generate, approve, send across platforms.

One run walks every new lead, picks the channel for its platform, and sends.
Default mode asks send/edit/skip per lead. AUTO_SEND=true sends automatically.
Per-platform daily limits and anti-ban delays apply.
"""
import random
import time

from app import config
from app.application.format_content import format_for_channel
from app.application.generate_message import GenerateMessage, subject_for
from app.application.send_outreach import SendOutreach
from app.domain.lead import STATUS_FAILED, STATUS_SENT, STATUS_SKIPPED
from app.infrastructure.channels.registry import build_channel
from app.infrastructure.cv_loader import load_cv_text, load_text_file
from app.infrastructure.openai_client import OpenAIMessageGenerator
from app.infrastructure.sheets_repo import SheetsRepo

_KNOWN = {"telegram", "linkedin", "hh", "email", "wellfound"}


def _prompt(msg: str) -> str:
    try:
        return input(msg).strip()
    except EOFError:
        return ""


def _show(message: str) -> None:
    print("\n--- СООБЩЕНИЕ ---\n" + message + "\n-----------------")


def run() -> None:
    print("== telegram-jobs sender (multi-platform) ==")
    cv_text = load_cv_text(config.CV_PATH)
    profile_text = load_text_file(config.PROFILE_PATH)

    repo = SheetsRepo(config.GOOGLE_SERVICE_ACCOUNT_FILE, config.SHEET_ID, config.SHEET_TAB)
    generator = GenerateMessage(
        OpenAIMessageGenerator(config.OPENAI_API_KEY, config.OPENAI_MODEL),
        cv_text, profile_text, config.SIGNATURE_TEXT,
    )

    leads = repo.fetch_new_leads()
    if not leads:
        print("Нет новых лидов (статус 'new'). Выход.")
        return

    mode = "АВТО (без подтверждения)" if config.AUTO_SEND else "ручной"
    print(f"Новых лидов: {len(leads)}. Лимит/платформа: {config.DAILY_SEND_LIMIT}. Режим: {mode}.")

    channels: dict[str, object] = {}     # platform -> started channel
    sent_per_platform: dict[str, int] = {}
    blocked: set[str] = set()            # platforms stopped by rate-limit

    def _channel_for(platform: str):
        if platform in channels:
            return channels[platform]
        ch = build_channel(platform, config)
        print(f"Подключаюсь к каналу '{platform}'...")
        ch.start()
        channels[platform] = ch
        return ch

    try:
        for lead in leads:
            platform = lead.platform
            if platform not in _KNOWN:
                repo.mark_status(lead, STATUS_SKIPPED, note=f"unknown platform: {platform}")
                print(f"⏭  Лид #{lead.lead_id}: неизвестная платформа '{platform}', пропуск.")
                continue
            if platform in blocked:
                repo.mark_status(lead, STATUS_SKIPPED, note="platform rate-limited this run")
                continue
            if sent_per_platform.get(platform, 0) >= config.DAILY_SEND_LIMIT:
                repo.mark_status(lead, STATUS_SKIPPED, note="daily limit reached")
                continue

            print("\n" + "=" * 60)
            print(f"Лид #{lead.lead_id}  [{platform}]  →  {lead.target}")
            print(f"Вакансия: {lead.vacancy_context or lead.raw_text}")
            print("-" * 60)

            try:
                channel = _channel_for(platform)
            except Exception as exc:  # noqa: BLE001
                repo.mark_status(lead, STATUS_FAILED, note=f"channel start failed: {exc}")
                print(f"❌ Не удалось поднять канал '{platform}': {exc}")
                continue

            sender = SendOutreach(channel)
            print("Генерирую сообщение...")
            body = generator.execute(lead)
            subject = subject_for(lead.vacancy_context or lead.raw_text)
            attachment = config.CV_PATH if config.ATTACH_CV else None
            content = format_for_channel(channel, body, subject, attachment)

            if not config.AUTO_SEND:
                _show(content.body)
                if "[" in content.body:
                    print("⚠️  Остался [плейсхолдер] — заполни через edit перед отправкой.")
                choice = _prompt("[s]end / [k]skip / [q]uit: ").lower()
                if choice in ("k", "skip"):
                    repo.mark_status(lead, STATUS_SKIPPED)
                    print("⏭  Пропущено.")
                    continue
                if choice in ("q", "quit"):
                    print("Выход по запросу.")
                    return

            result = sender.execute(lead, content)
            if result.ok:
                repo.mark_sent(lead, content.body, STATUS_SENT)
                sent_per_platform[platform] = sent_per_platform.get(platform, 0) + 1
                print(f"✅ Отправлено [{platform}] "
                      f"({sent_per_platform[platform]}/{config.DAILY_SEND_LIMIT}).")
                delay = random.randint(config.MIN_DELAY_SECONDS, config.MAX_DELAY_SECONDS)
                print(f"⏳ Пауза {delay} c (анти-бан)...")
                time.sleep(delay)
            elif result.rate_limited:
                repo.mark_status(lead, STATUS_SKIPPED, note="rate-limited")
                blocked.add(platform)
                print(f"🛑 Платформа '{platform}' ограничила нас — останавливаю её на этот запуск.")
            else:
                repo.mark_status(lead, STATUS_FAILED, note=result.error)
                print(f"❌ Ошибка отправки: {result.error}")
    finally:
        for ch in channels.values():
            try:
                ch.stop()
            except Exception:  # noqa: BLE001
                pass
        total = sum(sent_per_platform.values())
        print(f"\nГотово. Отправлено за сессию: {total}. По платформам: {sent_per_platform}")


if __name__ == "__main__":
    run()
