"""Domain entities for vacancy search. No external dependencies."""
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
    """`/jobs/` URLs are Easy-Apply targets; `/in/` URLs are recruiter DMs."""
    return "easy_apply" if "/jobs/" in url else "dm"
