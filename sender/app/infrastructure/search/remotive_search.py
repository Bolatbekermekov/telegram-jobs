"""Remotive searcher over the public JSON API (no browser, no login).

The public API (https://remotive.com/api/remote-jobs) IGNORES its search /
category / limit params (verified: every query returns the same cached
all-category feed), so we fetch the feed once and filter to relevant roles
ourselves on the title (app.domain.keyword_match), exactly like RemoteOK. Each
job carries its description, so describe() is served from a cache built during
search() — no second request, no extra AI cost on repeats.

ПЛОЩАДКА ИСЧЕРПАНА: бесплатно её потолок — ДВАДЦАТЬ вакансий.
--------------------------------------------------------------------------
Игнорируемые параметры — половина беды; вторая в том, что и сама лента
крошечная. Замеры 2026-08-27, всё живьём:

* `/api/remote-jobs` — 18 объектов, и это не срез: сам ответ сообщает
  `job-count: 18` и `total-job-count: 18`. По ключевым словам совпало 7,
  новых ноль. С `?limit=200`, `?category=software-dev`, `?search=engineer` —
  те же 18 бит в бит.
* RSS `https://remotive.com/remote-jobs/feed` — 20 записей: ровно те же
  вакансии плюс две, которые API прячет своей 24-часовой задержкой. Разница
  между лентами — двое суток свежести, а не объём. Ленты по разделам
  (`/remote-jobs/software-dev/feed`) отдают 404.
* HTML `https://remotive.com/remote-jobs` — те же 20 карточек, и `?page=2`
  отдаёт их же: страницы-«следующей» нет. Раздел
  `/remote-jobs/software-development` — 7 карточек.

Куда делось остальное, площадка говорит сама: на той же странице висит
«Unlock All Jobs — 10,653 added this week», то есть лента за подпиской, а в
юридической врезке ответа API — «We offer a private, paid-for API … (starting
budget is $5k/mo)». Полнее бесплатно НЕТ: ни RSS, ни HTML, ни параметров.

Отсюда правило чтения логов: «remotive: пусто» — это нормальный рабочий день
площадки, а не сбой. Сбой теперь виден отдельно (см. search() ниже: сеть
больше не гасится). Снимать площадку или нет — решение владельца; здесь
записан только измеренный факт, чтобы его не переоткрывали каждые полгода.
"""
import re

import httpx

from app.domain.candidate import KIND_JOB, Candidate, normalize_url
from app.domain.keyword_match import title_matches

REMOTIVE_API_URL = "https://remotive.com/api/remote-jobs"
DEFAULT_UA = "Mozilla/5.0 (compatible; telegram-jobs/1.0)"

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(text: str) -> str:
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", text or "")).strip()


def parse_remotive_jobs(payload: dict) -> list[dict]:
    """Pull the jobs array out of the API response (empty on malformed input)."""
    if not isinstance(payload, dict):
        return []
    return [j for j in payload.get("jobs", []) if isinstance(j, dict)]


def to_candidate(job: dict) -> Candidate:
    return Candidate(
        platform="remotive", kind=KIND_JOB,
        url=job.get("url", ""),
        title=job.get("title", ""),
        company=job.get("company_name", ""),
        salary=job.get("salary", "") or "",
        location=job.get("candidate_required_location", ""),
        summary="",
    )


class RemotiveSearcher:
    name = "remotive"

    def __init__(self, api_url: str = REMOTIVE_API_URL,
                 user_agent: str = DEFAULT_UA, timeout: int = 20):
        self._api_url = api_url
        self._ua = user_agent
        self._timeout = timeout
        self._desc: dict[str, str] = {}

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def _payload(self) -> dict:
        resp = httpx.get(
            self._api_url, headers={"User-Agent": self._ua},
            timeout=self._timeout, follow_redirects=True)
        resp.raise_for_status()
        return resp.json()

    def search(self, keywords_list, location, limit) -> list[Candidate]:
        self._desc.clear()  # fresh per run — don't accumulate across worker loops
        # Сбой сети не гасится — см. тот же комментарий в remoteok_search. Здесь
        # молчание было ещё дороже: у Remotive «ничего нового» — ОЖИДАЕМЫЙ ответ
        # (лента 18 вакансий, все уже виденные), и на его фоне упавший запрос не
        # заметил бы никто и никогда.
        jobs = parse_remotive_jobs(self._payload())
        found: list[Candidate] = []
        seen: set[str] = set()
        for job in jobs:
            if not title_matches(job.get("title", ""), keywords_list):
                continue
            key = normalize_url(job.get("url", ""))
            if not key or key in seen:
                continue
            seen.add(key)
            self._desc[key] = strip_html(job.get("description", ""))
            found.append(to_candidate(job))
            if len(found) >= limit:
                break
        return found

    def describe(self, url: str) -> str:
        return self._desc.get(normalize_url(url), "")
