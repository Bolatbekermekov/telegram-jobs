"""HeadHunter channel: applies to a vacancy (negotiation) via the official API."""
import re

import httpx

from app.domain.channel import ChannelError, OutreachContent, RateLimitedError

_API_BASE = "https://api.hh.ru"
_VACANCY_RE = re.compile(r"hh\.ru/vacancy/(\d+)")


def extract_vacancy_id(target: str) -> str:
    t = target.strip()
    if t.isdigit():
        return t
    m = _VACANCY_RE.search(t)
    if not m:
        raise ChannelError(f"cannot extract hh.ru vacancy id from: {target}")
    return m.group(1)


def post_negotiation(client, resume_id: str, vacancy_id: str, message: str) -> None:
    resp = client.post(
        f"{_API_BASE}/negotiations",
        data={"vacancy_id": vacancy_id, "resume_id": resume_id, "message": message},
    )
    if resp.status_code in (429, 403):
        raise RateLimitedError(f"hh.ru throttled/blocked: {resp.status_code}")
    if resp.status_code >= 400:
        raise ChannelError(f"hh.ru negotiation failed: {resp.status_code} {resp.text}")


class HeadHunterChannel:
    name = "hh"
    body_limit = None
    needs_subject = False

    def __init__(self, access_token: str, resume_id: str):
        self._token = access_token
        self._resume_id = resume_id
        self._client: httpx.Client | None = None

    def start(self) -> None:
        self._client = httpx.Client(
            headers={"Authorization": f"Bearer {self._token}",
                     "User-Agent": "telegram-jobs-sender/1.0"},
            timeout=30.0,
        )

    def stop(self) -> None:
        if self._client:
            self._client.close()

    def send(self, target: str, content: OutreachContent) -> None:
        if self._client is None:
            raise ChannelError("HeadHunterChannel.start() not called")
        vacancy_id = extract_vacancy_id(target)
        post_negotiation(self._client, self._resume_id, vacancy_id, content.body)
