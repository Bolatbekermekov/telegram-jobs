"""RemoteOK searcher over the public JSON API (no browser, no login).

The API (https://remoteok.com/api) returns the latest postings as a JSON array
whose FIRST element is a legal disclaimer (no job fields). Each job already
includes its description, so describe() is served from a cache built during
search() — no second request, no extra AI cost on repeats.
"""
import re

import httpx

from app.domain.candidate import KIND_JOB, Candidate, normalize_url

REMOTEOK_API_URL = "https://remoteok.com/api"
DEFAULT_UA = "Mozilla/5.0 (compatible; telegram-jobs/1.0)"

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"[a-z0-9+#]+")
# Seniority words carry no role signal — drop them so "junior backend developer"
# matches on its role words (backend / developer), not on the absent "junior".
_LEVEL_WORDS = {"junior", "jr", "intern", "internship", "senior", "sr",
                "mid", "entry", "level"}


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
        })
    return jobs


def job_matches(job: dict, keywords: list[str]) -> bool:
    """Match on the TITLE only, by role words.

    RemoteOK's public feed is all categories (its tags are noisy and its
    descriptions mention unrelated tech), so title words are the one clean
    signal. A job matches when any role word of any keyword (seniority words
    dropped) appears as a whole word in the title; the AI scorer then does the
    precise relevance filtering on the full description.
    """
    title_words = set(_WORD_RE.findall(job.get("title", "").lower()))
    for kw in keywords:
        role_words = [w for w in _WORD_RE.findall(kw.lower())
                      if w not in _LEVEL_WORDS]
        if role_words and any(w in title_words for w in role_words):
            return True
    return False


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
        jobs = parse_remoteok_jobs(self._payload())
        found: list[Candidate] = []
        for job in jobs:
            if not job_matches(job, keywords_list):
                continue
            self._desc[normalize_url(job["url"])] = strip_html(job["description"])
            found.append(to_candidate(job))
            if len(found) >= limit:
                break
        return found

    def describe(self, url: str) -> str:
        return self._desc.get(normalize_url(url), "")
