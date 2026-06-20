"""«Кандидаты» tab repository: append candidates with dedup + per-platform cap."""
import datetime as _dt

from app.domain.candidate import (
    CANDIDATE_COLUMNS, STATUS_PENDING, Candidate, normalize_url,
)


def candidate_to_row(c: Candidate, row_id, now: str) -> list:
    """Positional row matching CANDIDATE_COLUMNS."""
    return [
        row_id, c.platform, c.kind, c.url, c.title, c.company,
        c.salary, c.location, c.summary, STATUS_PENDING, now,
    ]


def should_add(c: Candidate, seen_keys: set, platform_pending: int, cap: int) -> bool:
    """New (normalized URL unseen) and the platform is under its pending cap."""
    if platform_pending >= cap:
        return False
    return normalize_url(c.url) not in seen_keys


class CandidatesRepo:
    def __init__(self, worksheet, main_worksheet, cap: int):
        self._ws = worksheet          # «Кандидаты» tab
        self._main = main_worksheet   # main leads tab (for cross-tab dedup)
        self._cap = cap

    def _ensure_header(self) -> None:
        if self._ws.row_values(1) != CANDIDATE_COLUMNS:
            self._ws.update("A1", [CANDIDATE_COLUMNS])

    def _seen_keys(self) -> set:
        keys = set()
        for url in self._ws.col_values(CANDIDATE_COLUMNS.index("URL") + 1)[1:]:
            if url:
                keys.add(normalize_url(url))
        # main tab: «Источник» column holds the URL for linkedin/wellfound leads
        from app.domain.lead import COLUMNS as MAIN
        for tgt in self._main.col_values(MAIN.index("Источник") + 1)[1:]:
            if tgt and "http" in tgt:
                keys.add(normalize_url(tgt))
        return keys

    def _pending_counts(self) -> dict:
        plats = self._ws.col_values(CANDIDATE_COLUMNS.index("Платформа") + 1)[1:]
        stats = self._ws.col_values(CANDIDATE_COLUMNS.index("Статус") + 1)[1:]
        counts: dict = {}
        for p, s in zip(plats, stats):
            if s == STATUS_PENDING:
                counts[p] = counts.get(p, 0) + 1
        return counts

    def _next_id(self) -> int:
        return max(len(self._ws.col_values(1)) - 1, 0) + 1

    def known_urls(self) -> set:
        """Normalized URLs already saved (Кандидаты + main tab), for pre-score dedup."""
        return self._seen_keys()

    def add_new(self, candidates) -> int:
        """Append candidates that pass dedup + cap. Returns how many were added."""
        self._ensure_header()
        seen = self._seen_keys()
        counts = self._pending_counts()
        now = _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        added = 0
        for c in candidates:
            if not should_add(c, seen, counts.get(c.platform, 0), self._cap):
                continue
            self._ws.append_row(candidate_to_row(c, self._next_id(), now),
                                value_input_option="USER_ENTERED", table_range="A1")
            seen.add(normalize_url(c.url))
            counts[c.platform] = counts.get(c.platform, 0) + 1
            added += 1
        return added
