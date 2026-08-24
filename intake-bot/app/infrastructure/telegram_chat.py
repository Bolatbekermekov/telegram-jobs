"""Человек это или канал — спрашиваем у самого Telegram.

Единственный вопрос, на который форма ника не отвечает. Bot API `getChat` по
публичному @нику отвечает точно (замерено 2026-08-24 этим же ботом):

    @devs_it         -> type=channel  «IT Jobs | Вакансии в IT»
    @simbirsoft_dev  -> type=channel  «SimbirSoft.Dev»
    @Adapty_Talent_Bot -> type=private  (бот, писать можно — и мы ему писали)
    @Bulavintseva_Mariya -> 400 «chat not found»

Последняя строка и задаёт форму ответа. Живого человека бот резолвить не умеет,
пока тот сам ему не написал, и «chat not found» приходит и на человека, и на
несуществующий ник. Значит доказать можно только ЗАПРЕТ: канал/группа — False,
всё остальное — None («не знаю»), и вызывающая сторона трактует незнание в
пользу лида.
"""
import json
import urllib.error
import urllib.parse
import urllib.request

# Куда писать нельзя: канал — вещание, группа — общий чат, и сопроводительное
# письмо в обоих случаях уходит не тому. `private` — человек ИЛИ бот; боты в
# найме обычная точка входа (@Adapty_Talent_Bot принял отклик), поэтому они
# проходят.
_UNWRITABLE = ("channel", "group", "supergroup")

# Ответ на один и тот же ник в пределах вызова функции не меняется, а пост часто
# повторяет ник подписи дважды. Контейнер Vercel живёт между запросами, так что
# кэш переживает и соседние сообщения — это ровно та память, которая тут нужна.
_cache: dict[str, bool | None] = {}


def _username(target: str) -> str:
    """'@nick', 'nick', 'https://t.me/nick' -> 'nick'. Пусто, если ника нет."""
    t = (target or "").strip().rstrip("/")
    lowered = t.lower()
    for prefix in ("https://t.me/", "http://t.me/", "t.me/",
                   "https://telegram.me/", "http://telegram.me/", "telegram.me/"):
        if lowered.startswith(prefix):
            t = t[len(prefix):]
            break
    t = t.lstrip("@").split("/")[0].split("?")[0]
    # Приглашение в закрытый чат (t.me/+AbCd, t.me/joinchat/…) ником не является:
    # getChat по нему всё равно ответит ошибкой, а запрос будет потрачен.
    if not t or t.startswith("+") or t.lower() == "joinchat":
        return ""
    return t


def is_writable_telegram_target(target: str, token: str, timeout: float = 4.0):
    """False — доказанный канал/группа; True — личный чат; None — неизвестно.

    Никогда не бросает: маршрутизация лида не должна зависеть от доступности
    Telegram. Все три ответа осмысленны, и None — самый частый.
    """
    name = _username(target)
    if not name or not token:
        return None
    if name in _cache:
        return _cache[name]

    url = ("https://api.telegram.org/bot" + token + "/getChat?"
           + urllib.parse.urlencode({"chat_id": "@" + name}))
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            kind = (json.load(resp).get("result") or {}).get("type", "")
        answer = False if kind in _UNWRITABLE else True if kind else None
    except urllib.error.HTTPError:
        answer = None      # «chat not found» — человек или пустышка, не различить
    except Exception:      # noqa: BLE001 — сеть, таймаут, мусор в ответе
        answer = None
    _cache[name] = answer
    return answer
