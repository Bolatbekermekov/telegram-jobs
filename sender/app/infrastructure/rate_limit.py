"""Переждать 429, а не считать его отказом.

Нужно из-за бесплатных тиров: Gemini flash отдаёт ~8 запросов в минуту,
flash-lite ~15, NVIDIA ~2. Пока лиды идут через паузу MIN/MAX_DELAY_SECONDS,
лимит недостижим — но пауза стоит ПОСЛЕ успешной отправки, и серия падений
(hh не показал поле письма, страница снята) прогоняет лиды вплотную. Прогон
2026-09-07 так и остановился: три 429 подряд на седьмом лиде из 81, и защита
«LLM недоступен» закончила прогон.

Сколько ждать, говорит сам провайдер: Gemini пишет «Please retry in 52.52279s»
в тексте ошибки (заголовка Retry-After он не присылает). Угадывать вредно в обе
стороны — короче названного значит потратить попытку впустую, длиннее значит
держать прогон на ровном месте. Лестница ниже нужна только когда срок не назван.
Ретраим ТОЛЬКО 429 — остальные ошибки отдаём наверх сразу,
чтобы прогон сам решил, отказ это или нет (см. generate_body).

Живёт только в sender: у бота на Vercel вся функция ограничена 10 секундами,
ждать там негде — он честно теряет оценку и пишет лид без неё.
"""
import re
import time
from typing import Callable, TypeVar

from openai import RateLimitError

T = TypeVar("T")

# Запасная лестница на случай, когда провайдер срок не назвал. Сумма с запасом
# перекрывает минуту — столько живёт окно квоты.
_WAITS_SECONDS = (20, 40, 65)

# Gemini кладёт срок в ТЕКСТ ошибки, заголовка Retry-After не присылает
# (проверено 2026-09-07): «Please retry in 52.52279s».
_RETRY_IN_RE = re.compile(r"retry in\s*([\d.]+)", re.I)

# Подождать чуть дольше названного: срок считается на стороне сервера, и
# запрос ровно в секунду срабатывания снова получает 429.
_BUFFER_SECONDS = 2
# Потолок, чтобы один ответ «retry in 3600» не остановил прогон на час.
_MAX_WAIT_SECONDS = 120


def _asked_delay(exc: Exception) -> float | None:
    """Сколько ждать по словам самого провайдера, или None если не сказал."""
    m = _RETRY_IN_RE.search(str(exc))
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def with_rate_limit_retry(call: Callable[[], T],
                          sleep: Callable[[float], None] | None = None) -> T:
    """Выполнить `call`, пережидая 429. Последний 429 пробрасывается наверх.

    `sleep` разрешается в момент ВЫЗОВА, а не в дефолте параметра: дефолт
    связался бы с `time.sleep` при определении функции, и подмена в тестах на
    него бы не подействовала — прогон тестов честно спал бы по две минуты.
    """
    sleep = sleep or time.sleep
    for fallback in _WAITS_SECONDS:
        try:
            return call()
        except RateLimitError as exc:
            asked = _asked_delay(exc)
            wait = fallback if asked is None else asked + _BUFFER_SECONDS
            sleep(min(wait, _MAX_WAIT_SECONDS))
    return call()
