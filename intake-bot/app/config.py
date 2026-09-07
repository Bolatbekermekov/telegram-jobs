"""Configuration loaded from environment (.env locally, Vercel env vars in cloud)."""
import os

from dotenv import load_dotenv

from app.llm_provider import resolve
from app.search_profile import SEARCH_PROFILE as _BUNDLED_SEARCH_PROFILE

load_dotenv()  # local .env; on Vercel the vars are injected and this is a no-op

# Кто обслуживает бота: openai или nvidia (см. app/llm_provider.py). Переменная
# своя, отдельная от ноутбука (SENDER_LLM_PROVIDER): у Vercel лимит функции
# 10 секунд, а модель здесь вызывается синхронно из вебхука, так что облако
# может остаться на OpenAI даже когда рассылка уже переехала.
LLM_PROVIDER = os.environ.get("INTAKE_LLM_PROVIDER", "").strip() or "openai"
_llm = resolve(LLM_PROVIDER, os.environ)
LLM_API_KEY = _llm.api_key
# None у OpenAI: SDK подставит свой адрес сам.
LLM_BASE_URL = _llm.base_url
# Summarising a pasted vacancy is extraction, not writing — the cheap tier is
# enough, and this runs on every message forwarded to the bot.
LLM_MODEL = _llm.model_cheap
OPENAI_MAX_OUTPUT_TOKENS = int(os.environ.get("OPENAI_MAX_OUTPUT_TOKENS", "1000"))

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
# Optional shared secret to validate Telegram webhook calls.
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")

# Google credentials. Local: a path to the JSON file (GOOGLE_SERVICE_ACCOUNT_FILE).
# Cloud (public repo, e.g. Vercel): paste the JSON content into GOOGLE_SERVICE_ACCOUNT_JSON.
GOOGLE_SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
SHEET_ID = os.environ["SHEET_ID"]
SHEET_TAB = os.environ.get("SHEET_TAB", "Лист1")

# Вкладка «Кандидаты» боту больше не нужна: подтверждение найденного убрано
# 2026-08-22, поиск на ноуте кладёт лид сразу в основную вкладку. Настройки
# CANDIDATES_TAB и SHOW_BATCH (сколько карточек слать пачкой) ушли вместе с ним;
# у ноутбучной половины CANDIDATES_TAB остался — она читает старую вкладку ради
# дедупликации.
CONTROL_TAB = os.environ.get("CONTROL_TAB", "Команды")
HEARTBEAT_STALE_SECONDS = int(os.environ.get("HEARTBEAT_STALE_SECONDS", "180"))

# Оценка «подходит ли пересланная вакансия» — тот же вопрос, который поиск на
# ноуте задаёт о каждой найденной. Профиль по умолчанию вшит в бандл (см.
# app/search_profile.py — .txt из sender/ в Vercel не доезжает); переменная
# окружения нужна, чтобы поправить профиль в облаке, не дожидаясь деплоя.
SEARCH_PROFILE = os.environ.get("SEARCH_PROFILE", "").strip() or _BUNDLED_SEARCH_PROFILE
# Порог назван и посчитан как у поиска (sender: MATCH_THRESHOLD=60), но делает
# здесь другое: ничего не отбрасывает. Постоянное указание владельца — никогда
# не пропускать вакансию молча, поэтому лид сохраняется при любой оценке, а
# порог решает лишь, предупредить ли о нём в ответе бота.
MATCH_THRESHOLD = int(os.environ.get("MATCH_THRESHOLD", "60"))
