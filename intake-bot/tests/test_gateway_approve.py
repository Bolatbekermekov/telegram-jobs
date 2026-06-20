from app.domain.lead import COLUMNS
from app.infrastructure.candidates_gateway import CANDIDATE_COLUMNS, CandidatesGateway


class _FakeWs:
    def __init__(self, values):
        self._values = values
        self.appended = []
        self.updated = []

    def col_values(self, c):
        return [r[c - 1] if len(r) >= c else "" for r in self._values]

    def row_values(self, i):
        return self._values[i - 1]

    def append_row(self, row, **kw):
        self.appended.append((row, kw))

    def update_cell(self, r, c, v):
        self.updated.append((r, c, v))


def _cand_row(cid="7"):
    return [cid, "linkedin", "job", "https://x/7", "Backend Dev", "Acme",
            "", "Remote", "80/100: fit", "pending", "2026-06-20"]


def test_approve_appends_to_main_anchored_at_A1_with_correct_columns():
    cand = _FakeWs([CANDIDATE_COLUMNS, _cand_row("7")])
    main = _FakeWs([COLUMNS])  # header only
    gw = CandidatesGateway(cand, main)

    assert gw.approve("7") is True
    assert len(main.appended) == 1
    row, kw = main.appended[0]
    # Must anchor to A1 so values land in columns A-J, not stray far-right columns.
    assert kw.get("table_range") == "A1"
    assert row[COLUMNS.index("Платформа")] == "linkedin"
    assert row[COLUMNS.index("Источник")] == "https://x/7"
    assert row[COLUMNS.index("Статус")] == "new"
