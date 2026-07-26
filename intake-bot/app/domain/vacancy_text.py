"""Deciding whether a message carries a vacancy, and pulling one out of hh HTML.

Pure text handling, no network — the fetching itself lives in
infrastructure/vacancy_fetcher.py so this stays testable on saved HTML.
"""
import html as _html
import re

_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
# What the hh iOS share sheet wraps around the link.
_SHARE_BOILERPLATE_RE = re.compile(
    r"sent via hh mobile app|отправлено из мобильного приложения hh|"
    r"^\s*vacancy\s*:|^\s*вакансия\s*:", re.IGNORECASE | re.MULTILINE)

# Below this, whatever is left after the links is too thin to summarise. Kept low
# on purpose: a real one-liner ("X is hiring a Junior AI Engineer, Ahmedabad,
# 2024-25 grads" — 91 chars) must count as text. Erring high is not free either,
# but it is safe: a needless fetch just returns a better description.
_MIN_MEANINGFUL_CHARS = 60


def is_link_only(text: str) -> bool:
    """True when the message is a bare link (plus share boilerplate).

    A phone share sends nothing but URLs. Handing that to the summariser gets a
    polite refusal back — the model has no web access — and that refusal is what
    ends up in the «Вакансия» column and, later, in the cover letter.
    """
    without_urls = _URL_RE.sub(" ", text or "")
    without_noise = _SHARE_BOILERPLATE_RE.sub(" ", without_urls)
    return len(without_noise.strip()) < _MIN_MEANINGFUL_CHARS


_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_RE = re.compile(r"<(script|style)\b.*?</\1>", re.IGNORECASE | re.DOTALL)
_WS_RE = re.compile(r"\s+")
_BLOCK_END_RE = re.compile(r"</(p|div|li|br|h[1-6])\s*/?>", re.IGNORECASE)

_TITLE_RE = re.compile(r'data-qa="vacancy-title"[^>]*>(.*?)</h1>', re.DOTALL)
_SALARY_RE = re.compile(r'data-qa="vacancy-salary[^"]*"[^>]*>(.*?)</span>', re.DOTALL)
_DESC_RE = re.compile(r'data-qa="vacancy-description"[^>]*>(.*?)(?=<div[^>]*data-qa=)',
                      re.DOTALL)


def _plain(markup: str, limit: int = 0) -> str:
    text = _SCRIPT_RE.sub(" ", markup or "")
    text = _BLOCK_END_RE.sub("\n", text)
    text = _TAG_RE.sub(" ", text)
    # Entities last, after tags: hh writes "Support &amp; QA", and a raw "&amp;"
    # in the summary prompt is noise the model has to guess its way around.
    text = _WS_RE.sub(" ", _html.unescape(text)).strip()
    return text[:limit] if limit else text


def extract_hh_vacancy(html: str, max_chars: int = 5000) -> str:
    """Title, salary and body of an hh vacancy page as plain text ("" if absent).

    Deliberately regex-based: the intake bot runs on a serverless function where
    an HTML parser is another dependency to install on every cold start, and all
    we need is the text inside three known `data-qa` blocks.
    """
    if not html:
        return ""
    desc = _DESC_RE.search(html)
    if not desc:
        return ""
    body = _plain(desc.group(1), max_chars)
    if not body:
        return ""

    head = []
    title = _TITLE_RE.search(html)
    if title:
        head.append(_plain(title.group(1), 200))
    salary = _SALARY_RE.search(html)
    if salary:
        s = _plain(salary.group(1), 100)
        if s:
            head.append(f"Зарплата: {s}")
    return "\n".join([*head, body]).strip()


# LinkedIn serves the public job view without a login, so these come off the same
# anonymous GET as hh — no session, and none of the ban risk that automating a
# logged-in LinkedIn carries.
_LI_TITLE_RE = re.compile(
    r'<h1[^>]*(?:top-card-layout__title|topcard__title)[^>]*>(.*?)</h1>', re.DOTALL)
_LI_COMPANY_RE = re.compile(r'topcard__org-name-link[^>]*>(.*?)</a>', re.DOTALL)
_LI_DESC_RE = re.compile(
    r'class="[^"]*(?:show-more-less-html__markup|description__text)[^"]*"[^>]*>(.*?)</div>',
    re.DOTALL)


def extract_linkedin_vacancy(html: str, max_chars: int = 5000) -> str:
    """Title, company and body of a LinkedIn job page as plain text ("" if absent)."""
    if not html:
        return ""
    desc = _LI_DESC_RE.search(html)
    if not desc:
        return ""
    body = _plain(desc.group(1), max_chars)
    if not body:
        return ""

    head = []
    title = _LI_TITLE_RE.search(html)
    if title:
        head.append(_plain(title.group(1), 200))
    company = _LI_COMPANY_RE.search(html)
    if company:
        c = _plain(company.group(1), 100)
        if c:
            head.append(f"Компания: {c}")
    return "\n".join([*head, body]).strip()


# A LinkedIn *post* (a hiring post, /posts/…) has none of the job-page selectors
# above — its text lives in the og:description meta tag, which carries the full
# post body (verified live 2026-07-22: ~1.5k chars for a real hiring post).
_LI_OG_DESC_RE = re.compile(
    r'<meta[^>]+(?:property|name)="(?:og:)?description"[^>]+content="([^"]*)"',
    re.IGNORECASE)
# When a post isn't publicly readable, LinkedIn serves its generic site blurb as
# og:description instead of the post — that is NOT the vacancy, so reject it
# (seen live on a post whose author restricts it).
_LI_POST_BOILERPLATE_RE = re.compile(
    r"manage your professional identity|"
    r"build and engage with your professional network|"
    r"\d[\d,\s]*million\+?\s*members", re.IGNORECASE)


def extract_linkedin_post(html: str, max_chars: int = 5000) -> str:
    """Body of a LinkedIn hiring post from its og:description meta ("" if absent
    or if LinkedIn served its generic members blurb — the post isn't public)."""
    if not html:
        return ""
    m = _LI_OG_DESC_RE.search(html)
    if not m:
        return ""
    # og:description is already plain text; just decode entities and keep the line
    # breaks (they separate the post's bullet points), don't collapse whitespace.
    text = _html.unescape(m.group(1)).strip()
    if not text or _LI_POST_BOILERPLATE_RE.search(text):
        return ""
    return text[:max_chars]
