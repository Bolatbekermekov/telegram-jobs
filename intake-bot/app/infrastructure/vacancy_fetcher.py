"""Fetch a vacancy page so a link-only message still gets a real description.

Every site is read anonymously, with a plain GET:

* hh — its public API answers 403 to an unauthenticated client (checked
  2026-07-20 on api.hh.ru/vacancies/<id>, every User-Agent), but the ordinary
  page comes back in well under a second.
* LinkedIn — the public job view AND hiring posts are served without a login, so
  this needs no session and carries none of the ban risk that automating a
  logged-in LinkedIn does. `/jobs/view/` is read from the job-page markup;
  `/posts/…` and `/feed/update/…` come back 200 (NOT 404 — that was stale) with
  the WHOLE post text in the og:description meta, line breaks and all (re-checked
  2026-08-13: 1243 chars of meta against a 1232-char rendered body). A DELETED post
  answers 404 with a ~320 KB generic shell to every User-Agent, crawlers included,
  which `_get` turns into "" before anything tries to parse it.
* lnkd.in — LinkedIn's own rewrite of any outbound url inside post text, and the
  second thing read here rather than a site of its own. It does not redirect; see
  `resolve_lnkd_in` below.
* Threads — the exact inverse of the two above: the server-rendered page comes
  back only to a NON-browser UA, and its og:description carries the ROOT post
  alone. The rest of the thread — the author's self-replies, where the contact to
  apply to usually sits — needs a real browser, so the sender reads it later from
  the laptop.

Best-effort by design: the bot runs on a serverless function with a short budget
and a datacenter IP that any of these sites may throttle, so every failure returns
"" and the caller falls back to summarising whatever the message itself contained.
"""
# The url predicates live in the domain module and are re-exported here on
# purpose. They are pure string tests, the application layer asks them too
# (application/extract_lead.py has to know a LinkedIn post from an hh page), and
# every existing caller — including the sender's cli — imports them from this
# module. Re-exporting keeps that spelling working while the definitions sit
# where a layer below the network can reach them.
from app.domain.vacancy_text import (  # noqa: F401 — re-exported, see above
    extract_external_url, extract_hh_vacancy, extract_linkedin_post,
    extract_linkedin_vacancy, extract_threads_post, is_fetchable_vacancy_url,
    is_hh_vacancy_url, is_linkedin_job_url, is_linkedin_post_url, is_lnkd_in_url,
    is_threads_post_url, iter_urls, pick_vacancy_url,
)

# A browser UA: a bot-looking one gets throttled by hh and LinkedIn.
_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# Threads is the exact inverse of hh/LinkedIn: it serves the server-rendered page
# (the one that carries og:description) only to a NON-browser client. Verified live
# 2026-07-26 — a browser UA gets a 258 KB JS shell with no og tags, an EMPTY UA gets
# nothing either, and so do the social-crawler UAs (facebookexternalhit, Twitterbot,
# TelegramBot, Slackbot). Plain HTTP-client UAs work: curl/*, python-httpx/*,
# python-requests/*, Python-urllib/*, Googlebot, and this one.
# Do NOT "unify" the two constants — that silently empties every Threads lead.
_CLIENT_UA = "vacancy-intake-bot/1.0"

# hh answers in ~0.6s and LinkedIn in ~2-3s, so this is head-room, not the norm.
# It stays small on purpose: the bot runs on a serverless function whose own
# budget is around 10s, and a fetch that outlives the function just turns a
# saved-without-description lead into a killed request that Telegram retries.
_TIMEOUT_SECONDS = 8.0

# Both sites throttle a burst of requests, which is what a backfill over many
# leads looks like. The pages come back fine a moment later, so one retry
# recovers most of it — three rows of an 11-row backfill, in the run that
# prompted this.
_RETRY_ATTEMPTS = 2
_RETRY_DELAY_SECONDS = 2.0

# The `lnkd.in` interstitial has its own budget rather than the page timeout: this
# runs inside a request that has already spent seconds reading a post, and the
# interstitial answers in ~0.4s. What it is and why it needs undoing at all is
# documented on `is_lnkd_in_url` in app/domain/vacancy_text.py.
_SHORTENER_TIMEOUT_SECONDS = 3.0


def _get(url: str, timeout: float, attempts: int = _RETRY_ATTEMPTS, sleep=None,
         *, ua: str = _UA) -> str:
    """GET `url`, retrying once on throttling or a network blip.

    A 403/404 is the site's final answer (restricted or removed vacancy) — retry
    it and you only wait longer for the same nothing.
    """
    import time

    import httpx

    _sleep = time.sleep if sleep is None else sleep
    for attempt in range(attempts):
        try:
            resp = httpx.get(url, headers={"User-Agent": ua}, timeout=timeout,
                             follow_redirects=True)
            if resp.status_code == 200:
                return resp.text
            if resp.status_code in (403, 404, 410):
                return ""
        except Exception:  # noqa: BLE001 — a timeout or reset is worth one retry
            if attempt == attempts - 1:
                return ""
        if attempt < attempts - 1:
            _sleep(_RETRY_DELAY_SECONDS * (attempt + 1))
    return ""


def resolve_lnkd_in(url: str, timeout: float = _SHORTENER_TIMEOUT_SECONDS) -> str:
    """The real address behind a `lnkd.in` short link, or "" if it can't be read.

    Refuses anything that is not `lnkd.in`, and that guard is the point rather
    than tidiness: the urls handed to this come out of a stranger's post text, so
    a resolver that fetched whatever it was given would let any hiring post pick a
    request the serverless function makes on its behalf.
    """
    url = (url or "").strip()
    if not is_lnkd_in_url(url):
        return ""
    try:
        return extract_external_url(_get(url, timeout))
    except Exception:  # noqa: BLE001 — a contact we can't recover is not a lost lead
        return ""


def fetch_vacancy_text(url: str, timeout: float = _TIMEOUT_SECONDS) -> str:
    """Vacancy text behind `url`, or "" if it can't be read for any reason."""
    url = (url or "").strip()
    ua = _UA
    if is_hh_vacancy_url(url):
        extract = extract_hh_vacancy
    elif is_linkedin_job_url(url):
        extract = extract_linkedin_vacancy
    elif is_linkedin_post_url(url):
        extract = extract_linkedin_post
    elif is_threads_post_url(url):
        extract = extract_threads_post
        ua = _CLIENT_UA          # a browser UA gets an empty JS shell here
    else:
        return ""
    try:
        return extract(_get(url, timeout, ua=ua))
    except Exception:  # noqa: BLE001 — never let intake fail over a missing description
        return ""


# Kept so an older import keeps working; new code should call fetch_vacancy_text.
fetch_hh_vacancy_text = fetch_vacancy_text
