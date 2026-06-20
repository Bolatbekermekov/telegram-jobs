"""Remotive searcher over the public JSON API (no browser, no login).

The API (https://remotive.com/api/remote-jobs?search=<kw>&limit=<n>) does the
keyword search server-side and returns each job WITH its description, so
describe() is served from a cache built during search() — no second request,
no extra AI cost on repeats.
"""
import re

import httpx

from app.domain.candidate import KIND_JOB, Candidate, normalize_url

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

    def _payload(self, keyword: str, limit: int) -> dict:
        resp = httpx.get(
            self._api_url, params={"search": keyword, "limit": limit},
            headers={"User-Agent": self._ua}, timeout=self._timeout,
            follow_redirects=True)
        resp.raise_for_status()
        return resp.json()

    def search(self, keywords_list, location, limit) -> list[Candidate]:
        from app.domain.search_request import per_keyword_limit
        self._desc.clear()  # fresh per run — don't accumulate across worker loops
        per_kw = per_keyword_limit(limit, len(keywords_list))
        found: list[Candidate] = []
        seen: set[str] = set()
        for kw in keywords_list:
            try:
                jobs = parse_remotive_jobs(self._payload(kw, per_kw))
            except Exception:  # noqa: BLE001 — one keyword failing must not kill the rest
                continue
            for job in jobs[:per_kw]:
                key = normalize_url(job.get("url", ""))
                if not key or key in seen:
                    continue
                seen.add(key)
                self._desc[key] = strip_html(job.get("description", ""))
                found.append(to_candidate(job))
                if len(found) >= limit:
                    return found
        return found

    def describe(self, url: str) -> str:
        return self._desc.get(normalize_url(url), "")
