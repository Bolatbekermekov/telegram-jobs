"""Register the intake bot's command menu via Telegram setMyCommands.

Run once (and after changing commands): `make bot_menu`. Reads TELEGRAM_BOT_TOKEN
from the project-root .env.
"""
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def bot_commands_payload() -> list[dict]:
    return [
        {"command": "start_search", "description": "Искать вакансии по всем платформам"},
        {"command": "search_linkedin", "description": "Искать вакансии в LinkedIn"},
        {"command": "search_wellfound", "description": "Искать вакансии в Wellfound"},
        {"command": "search_remoteok", "description": "Искать вакансии в RemoteOK"},
        {"command": "search_remotive", "description": "Искать вакансии в Remotive"},
        {"command": "search_hh", "description": "Искать вакансии в HeadHunter"},
        {"command": "status", "description": "Сводка по лидам (new / sent)"},
    ]


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("❌ TELEGRAM_BOT_TOKEN не задан в .env")
        return
    url = f"https://api.telegram.org/bot{token}/setMyCommands"
    data = urllib.parse.urlencode(
        {"commands": json.dumps(bot_commands_payload(), ensure_ascii=False)}).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10) as resp:
        print("setMyCommands:", resp.read().decode())


if __name__ == "__main__":
    main()
