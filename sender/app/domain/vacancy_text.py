"""Deciding whether a message carries a vacancy, and pulling one out of hh HTML.

Pure text handling, no network — the fetching itself lives in
infrastructure/vacancy_fetcher.py so this stays testable on saved HTML.
"""
import html as _html
import re
from urllib.parse import urlparse as _urlparse

from app.domain.contact import canonical_linkedin_url

# A url as MESSAGES actually carry one. The scheme is optional in real traffic: a
# phone paste and Telegram's own link text both drop it, which is why every rule in
# contact.py has always written it `(?:https?://)?`. Everything in THIS module
# required it, so `linkedin.com/jobs/view/…` was not a url here at all — and the
# damage was silent rather than an error: `is_link_only` counted the link's own 108
# characters as prose, so the message looked like it carried a description, the page
# was never fetched, and «Вакансия» became the summariser explaining that it cannot
# open links. Measured live 2026-08-22 on the X-FLOW job 4455783459.
#
# Scheme-less matching is bounded to the hosts this project handles and demands a
# path after the host, so ordinary prose stays prose: "пиши на hh.ru" has no path,
# and the left boundary keeps the host from matching inside an email address.
_KNOWN_HOST = (r"(?:[\w-]+\.)*(?:linkedin\.com|lnkd\.in|t\.me|telegram\.me|"
               r"hh\.(?:ru|kz|uz|by|kg|az|tj)|wellfound\.com|angel\.co|"
               r"remocate\.app|remoteok\.com|"
               r"threads\.(?:com|net))")
_URL_RE = re.compile(rf"https?://\S+|(?<![\w@.-]){_KNOWN_HOST}/\S*", re.IGNORECASE)
_SCHEME_RE = re.compile(r"^https?://", re.IGNORECASE)
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


# Sentence punctuation that `\S+` swallows but no url ends with. The same set
# `contact.py:_clean` strips off a detected contact, for the same reason: the url
# with the period stuck to it is a 404, and a lead read from it has no
# description at all.
_TRAILING = ".,);]>\"'"


def _absolute(url: str) -> str:
    """A matched url in the shape the fetch and every `is_*_url` test expect.

    Two normalisations, and both are load-bearing rather than tidy. The scheme,
    because a url without one is not something an http client will accept and not
    something the anchored predicates below will match. And LinkedIn's apex host,
    through the same helper `detect_contact` uses: `linkedin.com/jobs/view/…`
    answers 200 with a 20 KB shell that holds no advert, where the `www` host
    serves the whole page. `canonical_linkedin_url` is a no-op for every other
    host, which is why it can sit on the common path.
    """
    if not _SCHEME_RE.match(url):
        url = f"https://{url}"
    return canonical_linkedin_url(url)


def iter_urls(text: str):
    """Every url in `text` — absolute, trailing sentence punctuation trimmed."""
    for m in _URL_RE.finditer(text or ""):
        url = m.group(0).rstrip(_TRAILING)
        if url:
            yield _absolute(url)


# LinkedIn rewrites every outbound url inside post text as `lnkd.in/<code>`, so a
# `t.me` link an author put in their own hiring post is invisible to contact
# detection until the rewrite is undone. The rewrite does NOT answer 3xx: it
# answers 200 with a ~5 KB interstitial ("This link will take you to a page that's
# not on LinkedIn") whose only external anchor carries the real address. Verified
# live 2026-08-13; the fixture pair under tests/fixtures/linkedin pins both halves.
_LNKD_IN_RE = re.compile(r"^https?://lnkd\.in/", re.IGNORECASE)
_EXTERNAL_URL_RE = re.compile(
    r'data-tracking-control-name="external_url_click"[^>]*href="([^"]+)"',
    re.IGNORECASE)


def is_lnkd_in_url(url: str) -> bool:
    return bool(_LNKD_IN_RE.match((url or "").strip()))


def extract_external_url(html: str) -> str:
    """The destination an `lnkd.in` interstitial points at, or "" if absent."""
    m = _EXTERNAL_URL_RE.search(html or "")
    return _html.unescape(m.group(1)) if m else ""


# The share sheet appends its own tail to whatever it hands out:
# `?utm_source=share&utm_medium=member_desktop&rcm=<blob>`. The `rcm` blob
# identifies the person who shared, so it is not only noise in «Источник» — it
# rides along into every later fetch of that url. Params that ADDRESS a page
# (hh's `?text=python`) are left alone; only the known tracking names go.
_TRACKING_PARAM_RE = re.compile(
    r"^(?:utm_\w+|rcm|trk|trackingId|originalReferer)$", re.IGNORECASE)


def strip_tracking_params(url: str) -> str:
    """`url` without the share sheet's tracking params."""
    base, sep, rest = (url or "").strip().partition("?")
    if not sep:
        return base
    query, hash_sep, fragment = rest.partition("#")
    kept = [p for p in query.split("&")
            if p and not _TRACKING_PARAM_RE.match(p.partition("=")[0])]
    return base + ("?" + "&".join(kept) if kept else "") + hash_sep + fragment


# Each expansion is an http request inside a serverless budget of ~10s that still
# has a page read and a summary to pay for. Two is enough for a real message: a
# forwarded post carries one link, occasionally a second.
_MAX_EXPANDED_LINKS = 2


def expand_short_links(text: str, resolve_link, limit: int = _MAX_EXPANDED_LINKS) -> str:
    """`text` with LinkedIn's short links replaced by the addresses behind them.

    Sharing a POST gives `lnkd.in/p/<code>`, and that shape matches no contact
    rule and no fetchable-url rule — `detect_contact` answered None and intake
    replied «Не нашёл контакт» to a perfectly ordinary hiring post. Undoing the
    rewrite before anything else looks at the message is what makes it the
    ordinary `linkedin.com/posts/…` case the rest of the flow already handles.

    Only `lnkd.in` is ever handed to `resolve_link`: the urls in here come out of
    a message a stranger sent, and a resolver fed any of them would let the sender
    of that message choose a request this function makes on its behalf.
    """
    if resolve_link is None:
        return text or ""
    budget = limit

    def _swap(m):
        nonlocal budget
        matched = m.group(0)
        url = matched.rstrip(_TRAILING)
        # Tested and requested in absolute form, replaced by length of the ORIGINAL
        # match: a share that dropped the scheme is still the same short link.
        absolute = _absolute(url)
        if budget <= 0 or not is_lnkd_in_url(absolute):
            return matched
        budget -= 1
        try:
            resolved = resolve_link(absolute)
        except Exception:  # noqa: BLE001 — an unreachable shortener costs the
            # expansion, never the lead: the message is saved as it was written.
            return matched
        return resolved + matched[len(url):] if resolved else matched

    return _URL_RE.sub(_swap, text or "")


# --- which urls carry a vacancy ---------------------------------------------
# Pure string tests, so they live here rather than next to the fetch that uses
# them: `application/extract_lead.py` has to tell a LinkedIn post from an hh page
# to decide whether a message's own text is allowed to stand in for the page.
# `infrastructure/vacancy_fetcher.py` re-exports every name below, which is how
# the sender's cli and both test suites still reach them.

_HH_VACANCY_RE = re.compile(
    r"^https?://(?:[\w.-]*\.)?hh\.(?:ru|kz|uz|by|kg|az|tj)/vacancy/\d+", re.IGNORECASE)
# Both job-URL shapes: `/jobs/view/<id>` and the share form
# `/jobs/view/<slug>-<id>`. Only the first used to match, so a lead saved from a
# shared link was not even a candidate for the vacancy re-read (lead #169).
_LINKEDIN_JOB_RE = re.compile(
    r"^https?://(?:[\w.-]*\.)?linkedin\.com/jobs/view/(?:[^/?#]*-)?\d+",
    re.IGNORECASE)
_LINKEDIN_POST_RE = re.compile(
    r"^https?://(?:[\w.-]*\.)?linkedin\.com/(?:posts/|feed/update/)", re.IGNORECASE)
_THREADS_POST_RE = re.compile(
    r"^https?://(?:www\.)?threads\.(?:com|net)/@[\w.]+/post/[\w-]+", re.IGNORECASE)


def is_hh_vacancy_url(url: str) -> bool:
    return bool(_HH_VACANCY_RE.match((url or "").strip()))


def is_linkedin_job_url(url: str) -> bool:
    return bool(_LINKEDIN_JOB_RE.match((url or "").strip()))


def is_linkedin_post_url(url: str) -> bool:
    return bool(_LINKEDIN_POST_RE.match((url or "").strip()))


def is_threads_post_url(url: str) -> bool:
    return bool(_THREADS_POST_RE.match((url or "").strip()))


def is_fetchable_vacancy_url(url: str) -> bool:
    return (is_hh_vacancy_url(url) or is_linkedin_job_url(url)
            or is_linkedin_post_url(url) or is_threads_post_url(url)
            or is_aggregator_job_url(url) or is_remoteok_job_url(url))


def pick_vacancy_url(text: str) -> str:
    """The first url in `text` whose page can be read for a description, or "".

    Deliberately NOT `detect_contact`'s answer. That function decides whom to
    reply to and ranks a Telegram handle above every link, so a message carrying
    both a contact and a vacancy link would aim the fetch at the handle and never
    open the link — which is exactly how leads were saved with an empty
    «Вакансия» that nothing downstream could recover.
    """
    for url in iter_urls(text):
        if is_fetchable_vacancy_url(url):
            return url
    return ""


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


# A Threads post's text lives in og:description, like a LinkedIn post's — but with
# two differences that matter (both verified live 2026-07-26):
#
#  * Threads serves that markup ONLY to a non-browser User-Agent. A browser UA gets
#    a JS shell with no og tags at all, so the fetcher must NOT send `_UA` here.
#  * og:description carries the ROOT post only, capped around 480 chars. The rest of
#    the vacancy and the contact to apply to live in the author's self-replies, which
#    are absent from the anonymous HTML entirely. The sender re-reads the whole thread
#    in a browser; this is the cheap first pass that lets intake answer instantly.
#
# No boilerplate filter is needed (LinkedIn needs `_LI_POST_BOILERPLATE_RE`): a
# deleted or private Threads post comes back with no og tags, so it falls out here.
# Match og:description specifically, not `(?:og:)?description` — the page also carries
# a shorter plain `description` and a `twitter:description`, and relying on document
# order to pick the right one is a coin flip.
# Like `_LI_OG_DESC_RE`, this needs `property=` before `content=` and double quotes; a
# page that reorders the attributes or uses single ones yields "" rather than garbage.
_TH_OG_DESC_RE = re.compile(
    r'<meta[^>]+property="og:description"[^>]+content="([^"]*)"', re.IGNORECASE)


def extract_threads_post(html: str, max_chars: int = 5000) -> str:
    """Text of a Threads post from its og:description ("" when absent)."""
    if not html:
        return ""
    m = _TH_OG_DESC_RE.search(html)
    if not m:
        return ""
    # Already plain text: decode entities and keep the line breaks (they separate
    # the post's bullet points), don't collapse whitespace.
    text = _html.unescape(m.group(1)).strip()
    return text[:max_chars]


# --- агрегаторы вакансий -----------------------------------------------------
# Площадки, которые не нанимают сами, а ведут на сайт работодателя. Замер живьём
# 2026-08-22 на remocate.app: JSON-LD нет, og-тегов нет, meta description нет —
# только `<title>` вида «Software Engineering Intern (Winter) at Datadog», текст
# после снятия тегов начинается прямо с заголовка, а среди восьми внешних хостов
# страницы семь это шум (CDN Webflow, шрифты Google, соцсети и поддомены самого
# агрегатора) и ровно один — настоящий адрес отклика.
#
# Правило узкое, /jobs/<слаг>: главная и блог вакансиями не являются.
_AGGREGATOR_JOB_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?remocate\.app/jobs/[\w%-]+", re.IGNORECASE)
# RemoteOK держится отдельно от них НЕ по недосмотру: у него в sender'е свой
# канал — с переходом через /l/<id> и распознаванием платной стены, — и общий
# путь для агрегаторов это потерял бы.
_REMOTEOK_JOB_RE = re.compile(
    r"^(?:https?://)?(?:www\.)?remoteok\.com/remote-jobs/[\w%-]+", re.IGNORECASE)


def is_aggregator_job_url(url: str) -> bool:
    return bool(_AGGREGATOR_JOB_RE.match((url or "").strip()))


def is_remoteok_job_url(url: str) -> bool:
    return bool(_REMOTEOK_JOB_RE.match((url or "").strip()))


_SCRIPT_STYLE_RE = re.compile(r"(?is)<(script|style)[^>]*>.*?</\1>")
_ANY_TAG_RE = re.compile(r"(?s)<[^>]+>")
_HREF_RE = re.compile(r'href="(https?://[^"]+)"', re.IGNORECASE)
# Где кончается ОДНА вакансия и начинается лента чужих. Замер: «Apply for this
# job» стоит на 3894-м символе из 298607, и всё после него — карточки других
# компаний. Без обреза в бриф уезжает чужая вакансия, и письмо пишется по ней.
_VACANCY_END_MARKERS = ("Apply for this job", "Apply now", "Subscribe")
# Хвост длиннее этого не нужен даже без маркера: письмо пишется по сути, а не по
# всей странице, и лишнее только размывает бриф.
_VACANCY_TEXT_CAP = 4000
# Хосты, которые на странице агрегатора не могут быть работодателем.
_NOISE_HOSTS = (
    "googleapis.com", "gstatic.com", "google.com", "googletagmanager.com",
    "website-files.com", "cloudfront.net", "twitter.com", "x.com",
    "facebook.com", "instagram.com", "linkedin.com", "youtube.com",
    "t.me", "telegram.me",
)


def extract_aggregator_vacancy(html_text) -> str:
    """Текст одной вакансии со страницы агрегатора."""
    text = _SCRIPT_STYLE_RE.sub(" ", str(html_text or ""))
    text = _ANY_TAG_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", _html.unescape(text)).strip()
    if not text:
        return ""
    cut = len(text)
    for marker in _VACANCY_END_MARKERS:
        # Со сдвигом: маркер может стоять и в шапке (кнопка «Apply» дублируется
        # сверху), а обрезать по нему всю вакансию значит отдать пустой бриф.
        found = text.find(marker, 200)
        if found != -1:
            cut = min(cut, found)
    return text[:min(cut, _VACANCY_TEXT_CAP)].strip()


def _brand_of(page_url: str) -> str:
    """«www.remocate.app» -> «remocate». Нужен, чтобы отсечь поддомены сервисов
    САМОГО агрегатора: его касса и статус-страница живут на чужих доменах
    (lemonsqueezy, betteruptime), но имя агрегатора в хосте несут."""
    host = _urlparse(str(page_url or "")).netloc.lower().split(":")[0]
    parts = [p for p in host.split(".") if p and p != "www"]
    return parts[-2] if len(parts) >= 2 else (parts[0] if parts else "")


def aggregator_apply_url(html_text, page_url: str) -> str:
    """Настоящий адрес отклика со страницы агрегатора, или "" если он не один.

    Несколько кандидатов — это не повод выбирать: тот же принцип, что у точки
    входа Easy Apply, где угадывание между похожими контролами уводило прогон в
    чужую вакансию. Пусто здесь означает «пусть человек посмотрит сам», и это
    честнее, чем отклик не туда.
    """
    brand = _brand_of(page_url)
    by_host: dict = {}
    for href in _HREF_RE.findall(str(html_text or "")):
        host = _urlparse(href).netloc.lower()
        if not host or (brand and brand in host):
            continue
        if any(host == n or host.endswith("." + n) for n in _NOISE_HOSTS):
            continue
        by_host.setdefault(host, href)
    return next(iter(by_host.values())) if len(by_host) == 1 else ""
