"""Domain entities for vacancy search. No external dependencies."""
import re
from dataclasses import dataclass
from urllib.parse import urlsplit, urlunsplit

# Fixed column order of the «Кандидаты» sheet tab.
CANDIDATE_COLUMNS = [
    "id", "Платформа", "Тип", "URL", "Title", "Company",
    "Salary", "Location", "Summary", "Статус", "Дата",
]

STATUS_PENDING = "pending"
STATUS_TAKEN = "taken"
STATUS_REJECTED = "rejected"

KIND_JOB = "job"
KIND_PROFILE = "profile"


@dataclass
class Candidate:
    platform: str    # linkedin | wellfound | remoteok | remotive | hh
    kind: str        # job | profile
    url: str
    title: str
    company: str
    salary: str      # "" when the platform does not expose it
    location: str
    summary: str


def normalize_url(url: str) -> str:
    """Dedup key: lowercase host, drop query/fragment, strip trailing slash."""
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, "", ""))


def linkedin_action_for_url(url: str) -> str:
    """Classify a LinkedIn URL into an outreach action:
    - `/jobs/`                    -> "easy_apply" (in-platform application)
    - `/posts/` or `/feed/update/`-> "post" (a hiring post: message its author)
    - anything else (`/in/`)      -> "dm" (direct message a profile)."""
    if "/jobs/" in url:
        return "easy_apply"
    if "/posts/" in url or "/feed/update/" in url:
        return "post"
    return "dm"


# Автора поста дают два независимых источника, и адрес — первый из них: он
# ничего не стоит. У обычной ссылки на пост слаг начинается с ника автора:
#   /posts/<author-public-id>_<text-slug>-activity-<id>-<code>
# Хвост адреса — параметры и якорь — отрезается ДО поиска. Живой лид #525
# (2026-08-27): у «share»-ссылки `/posts/activity-7498…-FiK7?utm_source=share`
# ника автора нет вовсе, но подчёркивание в адресе есть — в `utm_source`, — и
# правило дотянулось до него через весь `activity-…`, выдав за автора
# `activity-7498303002928336896-FiK7?utm`. Из этого собрался несуществующий
# профиль, лид упал на «ни Сообщение, ни Контакт».
#
# Хуже того, непустой ответ отключил чтение автора СО СТРАНИЦЫ: оно включается
# только когда автора не нашли. Одна лишняя подстрока обесценивала весь
# запасной путь.
_QUERY_TAIL_RE = re.compile(r"[?#].*$", re.S)
_POST_AUTHOR_RE = re.compile(r"/posts/([^/_]+)_")


def post_author_profile_url(url: str) -> str | None:
    """Профиль автора поста, вынутый ИЗ АДРЕСА, или None, если его там нет.

    Ника в адресе нет у двух живых форм: `/feed/update/urn:li:activity:…` и
    «share»-ссылки из ленты по тегам — `/posts/hiring-react-remotejobs-share-
    <id>-<хеш>/`, где вместо ника стоят ХЕШТЕГИ. В прогоне 2026-08-27 оба
    поста-лида в очереди пришли второй формой и оба упали «не удалось
    определить автора»: взять его отсюда действительно неоткуда. Тогда автора
    снимают с самой страницы поста — см. `post_actor_profile_url`.
    """
    m = _POST_AUTHOR_RE.search(_QUERY_TAIL_RE.sub("", url or ""))
    if not m:
        return None
    return f"https://www.linkedin.com/in/{m.group(1)}/"


# Второй источник: ссылка на автора, снятая с открытой страницы поста. Сюда
# приходит только её href — какой разметкой он подписан, знает канал. Две формы,
# обе сняты живьём 2026-08-27:
#   https://www.linkedin.com/in/chrisguindon?miniProfileUrn=urn%3Ali%3Afsd_…  — человек
#   https://www.linkedin.com/company/eliza-black/posts                       — компания
# Хвост после ника (`?miniProfileUrn=…`, `/posts`) отбрасывается: профиль
# открывают чистым адресом, как и по быстрому пути выше.
_ACTOR_PROFILE_RE = re.compile(r"(?:^|linkedin\.com)/in/([^/?#]+)")
# Компания, витрина (`/showcase/`) и учебное заведение — это СТРАНИЦЫ, а не люди:
# ни «Сообщение», ни «Установить контакт» на них не бывает в принципе.
_ACTOR_ORG_RE = re.compile(r"(?:^|linkedin\.com)/(?:company|showcase|school)/")


def post_actor_profile_url(href: str) -> str | None:
    """Профиль ЧЕЛОВЕКА по ссылке на автора поста, или None, если это не человек.

    None здесь значит «писать некому», а не «не разобрал»: отличить одно от
    другого помогает `is_company_actor`, и канал отвечает на них по-разному.
    """
    m = _ACTOR_PROFILE_RE.search(href or "")
    if not m:
        return None
    return f"https://www.linkedin.com/in/{m.group(1)}/"


def is_company_actor(href: str) -> bool:
    """Пост опубликован страницей компании (витрины, вуза), а не человеком."""
    return bool(_ACTOR_ORG_RE.search(href or ""))
