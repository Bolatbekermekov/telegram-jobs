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
from app.domain.contact import detect_contact  # noqa: E402
from app.domain.telegram_message import message_text  # noqa: E402
from app.infrastructure.openai_client import OpenAISummarizer  # noqa: E402
from app.infrastructure.sheets_repo import SheetsRepo  # noqa: E402
from app.infrastructure.vacancy_fetcher import (  # noqa: E402
    fetch_vacancy_text, resolve_lnkd_in,
)
from app.infrastructure.control_gateway import ControlGateway  # noqa: E402

app = FastAPI()


def _reply(chat_id: int, text: str) -> None:
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10)
    except Exception:
        pass  # replying is best-effort; the lead is already saved


def _build_repo() -> SheetsRepo:
    return SheetsRepo(
        config.GOOGLE_SERVICE_ACCOUNT_FILE,
        config.GOOGLE_SERVICE_ACCOUNT_JSON,
        config.SHEET_ID,
        config.SHEET_TAB,
    )


def _build_use_case() -> ExtractLeadFromText:
    summarizer = OpenAISummarizer(config.OPENAI_API_KEY, config.OPENAI_MODEL)
    return ExtractLeadFromText(detect_contact, summarizer, _build_repo(),
                               fetcher=fetch_vacancy_text,
                               resolve_link=resolve_lnkd_in)


def _book():
    import gspread
    from google.oauth2.service_account import Credentials
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    if config.GOOGLE_SERVICE_ACCOUNT_JSON.strip():
        import json
        creds = Credentials.from_service_account_info(
            json.loads(config.GOOGLE_SERVICE_ACCOUNT_JSON), scopes=scopes)
    else:
        creds = Credentials.from_service_account_file(
            config.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=scopes)
    return gspread.authorize(creds).open_by_key(config.SHEET_ID)


def _control_gateway():
    return ControlGateway(_book().worksheet(config.CONTROL_TAB))


# Кнопок в боте больше нет, поэтому нет и отправки клавиатур с правкой карточек:
# `_reply_with_buttons` и `_edit_message` обслуживали ТОЛЬКО ✅/❌ у найденных
# вакансий. Подтверждение убрано (2026-08-22) — поиск кладёт лид сразу в
# основную вкладку, и телефону нечего решать.


def _do_start_search(chat_id: int, platform: str) -> None:
    from app.infrastructure.control_gateway import start_search_reply
    ctrl = _control_gateway()
    online = ctrl.is_worker_online(config.HEARTBEAT_STALE_SECONDS)
    ctrl.queue_search(platform)        # warn + queue regardless
    _reply(chat_id, start_search_reply(online))


def _handle_command(text: str, chat_id: int) -> bool:
    from app.domain.bot_commands import command_to_search_platform
    platform = command_to_search_platform(text)
    if platform is not None:
        _do_start_search(chat_id, platform)
        return True
    # `/show_vacancies` жил здесь до 2026-08-22 и показывал найденное с кнопками
    # ✅/❌. Подтверждение убрано целиком: поиск пишет лид сразу в основную
    # вкладку, и одобрять больше нечего. Команда не распознаётся намеренно —
    # пусть уйдёт в обычную ветку разбора сообщения, а не делает вид, что живёт.
    return False


# Human-readable labels for the statuses we know about, in display order.
_STATUS_LABELS = [
    ("new", "🆕 Новые"),
    ("sent", "✅ Отправлено"),
    ("skipped", "⏭ Пропущено"),
    ("failed", "❌ Ошибки"),
]


def _format_status(counts: dict) -> str:
    known = {key for key, _ in _STATUS_LABELS}
    lines = ["📊 Статус лидов"]
    for key, label in _STATUS_LABELS:
        lines.append(f"{label}: {counts.get(key, 0)}")
    for key in sorted(counts):
        if key not in known:
            lines.append(f"❔ {key}: {counts[key]}")
    lines.append(f"Всего: {sum(counts.values())}")
    return "\n".join(lines)


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

    # Нажатия на кнопки больше не приходят: клавиатур бот не шлёт с 2026-08-22.
    # Ответ на старую карточку, которая ещё висит у кого-то в переписке, надо
    # проглотить молча — Telegram иначе будет повторять апдейт.
    if update.get("callback_query"):
        return {"ok": True}

    message = update.get("message") or update.get("channel_post") or {}
    chat_id = (message.get("chat") or {}).get("id")
    # NOT `message["text"]`: a hyperlink's address never appears there — Telegram
    # keeps it in `entities` — and a post forwarded with its picture has no
    # `text` field at all. See app/domain/telegram_message.py.
    text = message_text(message)

    if not chat_id or not text:
        return {"ok": True}

    # Exact match only: `text.startswith("/start")` would also swallow /start_search,
    # which must reach _handle_command below.
    if text == "/start" or text.startswith("/start@"):
        _reply(
            chat_id,
            "Привет! Кидай текст вакансии — я вытащу контакт и сохраню лид в таблицу.\n"
            "Команда /status — сводка по лидам (сколько new / sent).\n"
            "Поиск: /start_search — по всем платформам, /search_linkedin, "
            "/search_wellfound, /search_remoteok, /search_remotive, /search_hh. "
            "Найденное сразу встаёт в очередь на отправку — одобрять не нужно.",
        )
        return {"ok": True}

    if text.startswith("/status"):
        try:
            _reply(chat_id, _format_status(_build_repo().count_by_status()))
        except Exception as exc:  # noqa: BLE001
            _reply(chat_id, f"❌ Не смог прочитать статус: {exc}")
        return {"ok": True}

    if _handle_command(text, chat_id):
        return {"ok": True}

    try:
        lead = _build_use_case().execute(text)
        extra = ""
        if lead.platform == "threads":
            # Phrased as a fact about the platform, NOT a claim about this fetch.
            # A fetch only happens for a link-only message, and even then it can
            # come back empty (post deleted, or Meta changes which UA gets the
            # server-rendered page). "Прочитан частично" would be false when the
            # message carried its own text, and in the empty case it would dress
            # up a total failure as a partial success.
            extra = ("\n\nℹ️ У Threads без браузера читается только первый пост — "
                     "полный тред и контакт для отклика дочитаю при отправке с ноута.")
        # An empty column means the link would not load in the seconds this
        # function had. Say that, rather than printing "Вакансия: " and letting it
        # read as a summary that came out blank — the lead is saved and the laptop
        # reads the link again before it sends anything.
        vacancy = lead.vacancy_context or (
            "не прочиталась сейчас — дочитаю при отправке с ноута")
        # A lead saved as «telegram / @acme_hr» from a message that named neither is
        # the one answer here that is genuinely surprising, so it says why. Without
        # it there is no way to tell a handle read out of a post from one typed by
        # hand — and so no way to notice it read the wrong one.
        routing = f"\nℹ️ {lead.note}" if lead.note else ""
        _reply(
            chat_id,
            f"✅ Сохранил лид\nПлатформа: {lead.platform}\nИсточник: {lead.target}"
            f"{routing}\nВакансия: {vacancy}{extra}",
        )
    except ValueError:
        _reply(
            chat_id,
            "⚠️ Не нашёл контакт. Пришли вакансию с одним из: @ник, t.me-ссылка, "
            "email, или ссылка LinkedIn / hh.ru / Wellfound / Threads.",
        )
    except Exception as exc:  # noqa: BLE001
        _reply(chat_id, f"❌ Ошибка при сохранении: {exc}")

    return {"ok": True}
