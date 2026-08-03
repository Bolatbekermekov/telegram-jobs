"""RemoteOK searcher over the public JSON API (no browser, no login).

The API (https://remoteok.com/api) returns the latest postings as a JSON array
whose FIRST element is a legal disclaimer (no job fields). Each job already
includes its description, so describe() is served from a cache built during
search() — no second request, no extra AI cost on repeats.
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
        try:
            payload = self._payload()
        except Exception:  # noqa: BLE001 — contain our own network failures
            return []
        jobs = parse_remoteok_jobs(payload)
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
