"""Send a one-off Telegram message via the bot API (best-effort, never raises)."""
import urllib.parse
import urllib.request


def send_telegram(token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=10)
    except Exception:  # noqa: BLE001 — notification is best-effort
        pass
