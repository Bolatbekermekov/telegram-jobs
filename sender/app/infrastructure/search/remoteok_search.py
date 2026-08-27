"""RemoteOK searcher over the public JSON API (no browser, no login).

The API (https://remoteok.com/api) returns the latest postings as a JSON array
whose FIRST element is a legal disclaimer (no job fields). Each job already
includes its description, so describe() is served from a cache built during
search() — no second request, no extra AI cost on repeats.

ЛЕНТА БОЛЬШАЯ, ОТКЛИК ЗАКРЫТ: 99 вакансий, подать можно на 3.
--------------------------------------------------------------------------
Замер 2026-08-27 (три недели назад было то же самое, см. can_apply):

* `https://remoteok.com/api` — 100 элементов, из них 99 вакансий. `original:
  true` у ТРЁХ, то есть 96 из 99 за платной подпиской.
* По ключевым словам совпало 7 названий. Три «совпавших и открытых» — это
  курсы по UX от Interaction Design Foundation, поймавшиеся на слово «AI» в
  «ai engineer»; профильных среди открытых нет.
* Параметр `tags` площадка, в отличие от Remotive, ЧЕСТНО обрабатывает:
  `?tags=dev|engineer|python|react|golang|backend|mobile` дают разные выдачи
  по ~99 вакансий (несуществующий `?tags=qa` — ноль, чем себя и выдаёт).
  Восемь запросов вместо одного дают 566 РАЗНЫХ вакансий — в шесть раз
  больше ленты. Только упирается это в ту же стену: открытых среди 566 всего
  СЕМЬ (1.2%) — три курса IxDF, три Lemon.io и один Product Engineer.
* `?limit=500` и `?offset=100` игнорируются (те же 99). RSS
  `https://remoteok.com/remote-jobs.rss` — HTTP 410 Gone.

То есть узкое место здесь не размер ленты, а `can_apply`: сколько её ни
расширяй тегами, отклик открыт на один процент. Обход по тегам — рычаг
рабочий и измеренный (3 доступные вакансии с одного запроса против 7 с
восьми), но платить за него надо восемью запросами в прогон ради четырёх
вакансий. Включать его — как и снимать площадку — без слова владельца
нельзя.
"""
import re

import httpx

from app.domain.candidate import KIND_JOB, Candidate, normalize_url
from app.domain.keyword_match import title_matches

REMOTEOK_API_URL = "https://remoteok.com/api"
DEFAULT_UA = "Mozilla/5.0 (compatible; telegram-jobs/1.0)"

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(text: str) -> str:
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", text or "")).strip()


def format_salary(lo, hi) -> str:
    lo = int(lo or 0)
    hi = int(hi or 0)
    if lo <= 0 and hi <= 0:
        return ""
    if lo > 0 and hi > 0:
        return f"${lo:,}–${hi:,}"
    return f"${(lo or hi):,}"


def parse_remoteok_jobs(payload: list) -> list[dict]:
    """Drop the disclaimer element; keep entries that look like jobs."""
    jobs = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        if not item.get("id") or not item.get("position"):
            continue  # disclaimer / malformed
        jobs.append({
            "id": str(item.get("id")),
            "title": item.get("position", ""),
            "company": item.get("company", ""),
            "location": item.get("location", "") or "Remote",
            "tags": [str(t) for t in (item.get("tags") or [])],
            "description": item.get("description", ""),
            "url": item.get("url", ""),
            "salary_min": item.get("salary_min", 0),
            "salary_max": item.get("salary_max", 0),
            # Разместил ли вакансию сам работодатель. Решает, можно ли вообще
            # откликнуться — см. can_apply().
            "original": bool(item.get("original")),
        })
    return jobs


def can_apply(job: dict) -> bool:
    """Открыт ли отклик на эту вакансию бесплатному аккаунту.

    Замер живой ленты 2026-08-03: из 100 вакансий поле `original: true` было
    ровно у двух — и ровно они открылись по кнопке Apply (одна на форму Ashby,
    вторая на почту работодателя). Остальные 98 упёрлись в экран подписки
    RemoteOK Premium ($14.95/мес, 12 месяцев), и бесплатного выхода с него нет:
    на экране только две кнопки оплаты, а замеченный в его же ссылке параметр
    skip_premium=1 просто возвращает на страницу вакансии.

    Возрастом это не объясняется — за экраном и однодневные вакансии, и
    четырёхдневные, а вся лента и есть четыре дня. И это не квота на отклики:
    повторный заход на те же три вакансии дал тот же результат бит в бит.
    `original` — это вакансии, размещённые работодателем напрямую; остальное
    RemoteOK собрал с чужих сайтов и продаёт доступ к ссылке.

    Перепроверено 2026-08-27: 3 из 99 в ленте и 7 из 566 при обходе по тегам
    (1.2%). За три недели доля не сдвинулась — это не разовая невезуха и не
    временная акция площадки, а её бизнес-модель.
    """
    return bool(job.get("original"))


def job_matches(job: dict, keywords: list[str]) -> bool:
    """Match on the TITLE only, by role words (see app.domain.keyword_match).

    RemoteOK's public feed is all categories with noisy tags and descriptions
    that mention unrelated tech, so the title is the one clean signal; the AI
    scorer does the precise relevance filtering on the full description.
    """
    return title_matches(job.get("title", ""), keywords)


def to_candidate(job: dict) -> Candidate:
    return Candidate(
        platform="remoteok", kind=KIND_JOB,
        url=job.get("url", ""),
        title=job.get("title", ""),
        company=job.get("company", ""),
        salary=format_salary(job.get("salary_min"), job.get("salary_max")),
        location=job.get("location", ""),
        summary="",
    )


class RemoteOKSearcher:
    name = "remoteok"

    def __init__(self, api_url: str = REMOTEOK_API_URL,
                 user_agent: str = DEFAULT_UA, timeout: int = 20):
        self._api_url = api_url
        self._ua = user_agent
        self._timeout = timeout
        self._desc: dict[str, str] = {}

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def _payload(self) -> list:
        resp = httpx.get(self._api_url, headers={"User-Agent": self._ua},
                         timeout=self._timeout, follow_redirects=True)
        resp.raise_for_status()
        return resp.json()

    def search(self, keywords_list, location, limit) -> list[Candidate]:
        self._desc.clear()  # fresh per run — don't accumulate across worker loops
        # Сбой сети НЕ гасится: он летит наружу, run_search ловит его и называет
        # через on_error — «⚠️ remoteok: 429 …» в консоли и «ошибка» вместо
        # «пусто» в отчёте, ровно как у соседних площадок.
        #
        # Раньше здесь стоял `except Exception: return []`, и это была ложь,
        # которую нечем было поймать: пустая выдача у RemoteOK — НОРМА (замер
        # 2026-08-27: 99 вакансий в ленте, отклик открыт на 3), поэтому упавший
        # запрос выглядел точно так же, как обычный день без совпадений.
        jobs = parse_remoteok_jobs(self._payload())
        found: list[Candidate] = []
        for job in jobs:
            # Отбор ДО скоринга: вакансия, на которую нельзя подать заявку, не
            # должна ни стоить вызова модели, ни попадать в очередь человеку.
            if not can_apply(job):
                continue
            if not job_matches(job, keywords_list):
                continue
            self._desc[normalize_url(job["url"])] = strip_html(job["description"])
            found.append(to_candidate(job))
            if len(found) >= limit:
                break
        return found

    def describe(self, url: str) -> str:
        return self._desc.get(normalize_url(url), "")
