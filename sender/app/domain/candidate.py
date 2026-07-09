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
    platform: str    # linkedin | wellfound | remoteok | remotive | wwr
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


# A post URL embeds the author's public id in its slug:
#   /posts/<author-public-id>_<text-slug>-activity-<id>-<code>
_POST_AUTHOR_RE = re.compile(r"/posts/([^/_]+)_")


def post_author_profile_url(url: str) -> str | None:
    """Return the profile URL of a post's author, or None if it can't be parsed
    (e.g. a company `/feed/update/` share with no personal author in the slug)."""
    m = _POST_AUTHOR_RE.search(url)
    if not m:
        return None
    return f"https://www.linkedin.com/in/{m.group(1)}/"
