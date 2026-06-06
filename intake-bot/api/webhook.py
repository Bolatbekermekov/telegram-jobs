"""Vercel serverless entrypoint: Telegram webhook for the intake bot.

Flow: Telegram POSTs an update -> extract lead via OpenAI -> append to Google Sheet
-> reply to the user with what was saved.
"""
import sys
import urllib.request
import urllib.parse
from pathlib import Path

# Make `app` importable when Vercel runs this file.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, Header, Request  # noqa: E402

from app import config  # noqa: E402
from app.application.extract_lead import ExtractLeadFromText  # noqa: E402
from app.infrastructure.openai_client import OpenAIExtractor  # noqa: E402
from app.infrastructure.sheets_repo import SheetsRepo  # noqa: E402

app = FastAPI()


def _reply(chat_id: int, text: str) -> None:
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10)
    except Exception:
        pass  # replying is best-effort; the lead is already saved


def _build_use_case() -> ExtractLeadFromText:
    extractor = OpenAIExtractor(config.OPENAI_API_KEY, config.OPENAI_MODEL)
    repo = SheetsRepo(config.GOOGLE_SERVICE_ACCOUNT_JSON, config.SHEET_ID, config.SHEET_TAB)
    return ExtractLeadFromText(extractor, repo)


@app.get("/")
def health():
    return {"ok": True, "service": "telegram-jobs-intake"}


@app.post("/")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(default=""),
):
    if config.TELEGRAM_WEBHOOK_SECRET and (
        x_telegram_bot_api_secret_token != config.TELEGRAM_WEBHOOK_SECRET
    ):
        return {"ok": False, "error": "bad_secret"}

    update = await request.json()
    message = update.get("message") or update.get("channel_post") or {}
    chat_id = (message.get("chat") or {}).get("id")
    text = (message.get("text") or "").strip()

    if not chat_id or not text:
        return {"ok": True}

    if text.startswith("/start"):
        _reply(chat_id, "Привет! Кидай текст вакансии — я вытащу контакт и сохраню лид в таблицу.")
        return {"ok": True}

    try:
        lead = _build_use_case().execute(text)
        _reply(
            chat_id,
            f"✅ Сохранил лид\nКонтакт: {lead.nickname}\nВакансия: {lead.vacancy_context}",
        )
    except ValueError:
        _reply(chat_id, "⚠️ Не нашёл @ник или t.me-ссылку в тексте. Добавь контакт и пришли снова.")
    except Exception as exc:  # noqa: BLE001
        _reply(chat_id, f"❌ Ошибка при сохранении: {exc}")

    return {"ok": True}
