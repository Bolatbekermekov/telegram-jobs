"""Search-request entity exchanged via the «Команды» tab. No external deps."""
from dataclasses import dataclass

REQ_PENDING = "pending"
REQ_RUNNING = "running"
REQ_DONE = "done"
REQ_ERROR = "error"

# Platforms searchable in sub-project C, in scrape order.
SEARCH_PLATFORMS = ["linkedin", "wellfound", "remoteok", "remotive", "remocate",
                    "hh"]


@dataclass
class SearchRequest:
    id: str
    platform: str   # all | linkedin | wellfound
    status: str


def platforms_for(platform: str) -> list[str]:
    """Expand a request's platform field into the concrete platforms to scrape."""
    if platform == "all":
        return list(SEARCH_PLATFORMS)
    return [platform]


def per_keyword_limit(total: int, n_keywords: int, per_keyword: int) -> int:
    """Потолок на ОДИН запрос: `per_keyword`, но не больше бюджета платформы.

    Бюджет между словами больше не делится. Старое правило считало
    max(1, total // n_keywords), и с девятью словами при бюджете 15 это давало
    ровно ОДНУ карточку на запрос — всегда одну и ту же, потому что LinkedIn
    сортирует выдачу по релевантности, а не по дате. Замер листа: 36 кандидатов
    в первый день и 4–11 в каждый следующий, всё остальное отсеивалось как
    дубль. При том что на странице LinkedIn лежит 25 вакансий, а по одному
    только слову «ai engineer» за неделю их больше восьми тысяч.

    Перебор останавливает уже сам вызывающий, когда наберёт `total`.

    Ноль в любой из настроек значит «ограничения с этой стороны нет», а не «ноль
    карточек»: опечатка в .env не должна молча выключать поиск целиком.
    """
    if n_keywords <= 0:
        return total
    ceilings = [v for v in (per_keyword, total) if v > 0]
    return max(1, min(ceilings)) if ceilings else 1
