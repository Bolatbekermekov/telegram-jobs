"""Поиск по Jobicy через открытый JSON API: без браузера, без логина, без ключа.

Замеры живьём 2026-09-11 на `jobicy.com/api/v2/remote-jobs`:

* параметр `tag` РАБОТАЕТ — и это главное отличие от Remotive, чьи параметры
  лента игнорирует целиком. `tag=golang` отдаёт 59, `tag=node.js` — 69, а
  пересечение выдач `python` и `ai engineer` всего 27 из 100: это разные
  наборы, а не одна и та же лента под разными именами. Поэтому спрашиваем
  ПОЗАПРОСНО по каждому ключевому слову, а не режем один общий ответ;
* фраза тоже работает: `tag=ai engineer` возвращает настоящие «AI Engineer …»
  первыми строками;
* фильтр полнотекстовый, по описанию тоже: в выдаче `tag=python` слово Python
  стоит в ЗАГОЛОВКЕ лишь у 10 вакансий из 100. Поэтому заголовок всё равно
  проверяется своим `title_matches`, как у Remotive и RemoteOK, — иначе в
  очередь поедут продакты и рекрутёры, упомянувшие Python в требованиях к
  команде, и каждый будет стоить вызова модели и письма;
* потолок ответа — 100 вакансий на запрос (`count`), ответы кешируются
  (`x-jobicy-api-cache`), Cloudflare анонимный GET не блокирует.

Отклик этой площадкой НЕ обслуживается, и это измеренный факт, а не упущение:
кнопка «Apply Now» на странице вакансии — не ссылка, а `<button>` с событием
`RegistrationGateOpened`; адреса работодателя нет ни в разметке страницы, ни в
пред-отрисованном попапе, ни в `jobDescription` (проверено на 50 вакансиях:
ноль ссылок в ATS). Jobicy отдаёт его только зарегистрированным.
"""
import re

import httpx

from app.domain.candidate import KIND_JOB, Candidate, normalize_url
from app.domain.keyword_match import title_matches

JOBICY_API_URL = "https://jobicy.com/api/v2/remote-jobs"
DEFAULT_UA = "Mozilla/5.0 (compatible; telegram-jobs/1.0)"
# Потолок самой площадки: больше ста она не отдаёт ни при каком `count`.
_MAX_COUNT = 100

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(text: str) -> str:
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", text or "")).strip()


def parse_jobicy_jobs(payload) -> list[dict]:
    """Массив вакансий из ответа API (пусто на любой неожиданной форме)."""
    if not isinstance(payload, dict):
        return []
    return [j for j in payload.get("jobs", []) if isinstance(j, dict)]


def _salary(job: dict) -> str:
    """Вилка строкой, или "" — у большинства вакансий Jobicy её нет вовсе."""
    low = job.get("annualSalaryMin") or ""
    high = job.get("annualSalaryMax") or ""
    cur = job.get("salaryCurrency") or ""
    if not low and not high:
        return ""
    return " ".join(p for p in (f"{low}-{high}".strip("-"), cur) if p)


def to_candidate(job: dict) -> Candidate:
    return Candidate(
        platform="jobicy", kind=KIND_JOB,
        url=job.get("url", ""),
        title=job.get("jobTitle", ""),
        company=job.get("companyName", ""),
        salary=_salary(job),
        # `jobGeo` приходит строкой вида «APAC, EMEA, LATAM, Canada, USA» —
        # это список разрешённых регионов, а не адрес офиса.
        location=(job.get("jobGeo") or "").strip(),
        summary="",
    )


def _fetch_tag(tag: str, count: int, api_url: str = JOBICY_API_URL,
               user_agent: str = DEFAULT_UA, timeout: int = 20) -> dict:
    resp = httpx.get(api_url, params={"count": count, "tag": tag},
                     headers={"User-Agent": user_agent}, timeout=timeout,
                     follow_redirects=True)
    resp.raise_for_status()
    return resp.json()


class JobicySearcher:
    name = "jobicy"

    def __init__(self, api_url: str = JOBICY_API_URL,
                 user_agent: str = DEFAULT_UA, timeout: int = 20, fetch=None):
        self._api_url = api_url
        self._ua = user_agent
        self._timeout = timeout
        # Инъекция ради тестов, ровно как `fetch_text` у HHSearcher: сеть живёт
        # в одной функции, а поведение поиска проверяется без неё.
        self._fetch = fetch or (
            lambda tag, count: _fetch_tag(tag, count, self._api_url, self._ua,
                                          self._timeout))
        self._desc: dict[str, str] = {}

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def search(self, keywords_list, location, limit) -> list[Candidate]:
        # `location` не используется: площадка отдаёт только удалёнку, а её
        # `jobGeo` — это список разрешённых регионов, не адрес. Фильтровать по
        # нему значило бы выбрасывать вакансии, открытые «EMEA», под которые
        # Казахстан подходит.
        self._desc.clear()          # свежий кэш на прогон, не копим между циклами
        found: list[Candidate] = []
        seen: set[str] = set()
        for keyword in keywords_list:
            if len(found) >= limit:
                break
            # Сбой сети НЕ гасится: он летит наружу, run_search ловит его и
            # называет ошибкой. Пустая выдача у площадки — нормальный рабочий
            # день, и заглушенный 429 был бы от неё неотличим.
            jobs = parse_jobicy_jobs(self._fetch(keyword, _MAX_COUNT))
            for job in jobs:
                url = job.get("url") or ""
                if not url:
                    continue
                key = normalize_url(url)
                if key in seen:
                    continue
                # Заголовок проверяем своим правилом: фильтр площадки
                # полнотекстовый и тащит всех, кто просто упомянул технологию.
                if not title_matches(job.get("jobTitle", ""), keywords_list):
                    continue
                seen.add(key)
                self._desc[key] = strip_html(job.get("jobDescription", ""))
                found.append(to_candidate(job))
                if len(found) >= limit:
                    break
        return found

    def describe(self, url: str) -> str:
        return self._desc.get(normalize_url(url), "")
