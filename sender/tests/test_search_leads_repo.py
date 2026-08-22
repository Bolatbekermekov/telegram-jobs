"""Найденная вакансия становится лидом сразу, без ручного approve.

Раньше поиск писал во вкладку «Кандидаты» со статусом `pending`, а в main tab
строка попадала только после кнопки ✅ в боте. По решению владельца (2026-08-22)
подтверждения больше нет: что нашлось и прошло скоринг, то и уходит в работу.

Вкладка «Кандидаты» остаётся ТОЛЬКО как память: новых строк туда не пишется, но
старые продолжают участвовать в дедупликации — в том числе отклонённые когда-то
кнопкой ❌, чтобы они не полезли обратно теперь, когда отклонять нечем.
"""
from app.domain.candidate import CANDIDATE_COLUMNS, Candidate, normalize_url
from app.domain.lead import COLUMNS, STATUS_NEW
from app.infrastructure.search_leads_repo import (
    SearchLeadsRepo, candidate_to_lead_row, should_add,
)


def _cand(url="https://linkedin.com/jobs/view/1", platform="linkedin",
          title="Backend Engineer", company="Acme", salary="$5k",
          location="Remote", summary="Пишем на Python."):
    return Candidate(platform=platform, kind="job", url=url, title=title,
                     company=company, salary=salary, location=location,
                     summary=summary)


def _col(row, name):
    return row[COLUMNS.index(name)]


class _FakeWs:
    """Ровно та часть gspread, которой пользуется репозиторий."""

    def __init__(self, rows=None, header=None):
        self.header = header or []
        self.rows = [list(r) for r in (rows or [])]
        self.appended = []

    def col_values(self, n):
        head = [self.header[n - 1]] if len(self.header) >= n else [""]
        return head + [r[n - 1] if len(r) >= n else "" for r in self.rows]

    def append_row(self, values, **kw):
        self.appended.append(values)
        self.rows.append(list(values))


def _main(rows=None):
    return _FakeWs(rows=rows, header=COLUMNS)


def _legacy(rows=None):
    return _FakeWs(rows=rows, header=CANDIDATE_COLUMNS)


def _lead_row(url, platform="linkedin", status=STATUS_NEW, row_id="1"):
    row = [""] * len(COLUMNS)
    row[COLUMNS.index("id")] = row_id
    row[COLUMNS.index("Платформа")] = platform
    row[COLUMNS.index("Источник")] = url
    row[COLUMNS.index("Статус")] = status
    return row


def _cand_row(url, status="rejected"):
    row = [""] * len(CANDIDATE_COLUMNS)
    row[CANDIDATE_COLUMNS.index("URL")] = url
    row[CANDIDATE_COLUMNS.index("Статус")] = status
    return row


# --- строка лида -------------------------------------------------------------

def test_a_found_job_becomes_a_new_lead_row():
    row = candidate_to_lead_row(_cand(), 7, "2026-08-22 15:00")

    assert len(row) == len(COLUMNS)
    assert _col(row, "id") == 7
    assert _col(row, "Статус") == STATUS_NEW
    assert _col(row, "Платформа") == "linkedin"
    assert _col(row, "Источник") == "https://linkedin.com/jobs/view/1"
    assert _col(row, "Дата добавления") == "2026-08-22 15:00"
    # Ничего не отправлено — эти колонки обязаны быть пустыми, иначе прогон
    # прочитает лид как уже обработанный.
    assert _col(row, "Сообщение") == ""
    assert _col(row, "Дата отправки") == ""


def test_the_company_survives_into_the_vacancy_text():
    """Письмо пишется по этой колонке. Работодателя в ней надо назвать по имени,
    а вилку и локацию — упомянуть, если площадка их отдала."""
    vacancy = _col(candidate_to_lead_row(_cand(), 1, "now"), "Вакансия")

    assert "Backend Engineer" in vacancy
    assert "Acme" in vacancy
    assert "$5k" in vacancy
    assert "Remote" in vacancy
    assert "Пишем на Python." in vacancy


def test_fields_the_platform_did_not_give_leave_no_empty_labels():
    c = _cand(company="", salary="", location="")
    vacancy = _col(candidate_to_lead_row(c, 1, "now"), "Вакансия")

    assert "Зарплата" not in vacancy
    assert "Локация" not in vacancy
    assert vacancy.startswith("Backend Engineer")


# --- дедуп и потолок ---------------------------------------------------------

def test_should_add_accepts_a_fresh_url_under_the_cap():
    assert should_add(_cand(), set(), 0, 60) is True


def test_should_add_refuses_a_url_we_have_seen():
    seen = {normalize_url("https://linkedin.com/jobs/view/1")}
    assert should_add(_cand(), seen, 0, 60) is False


def test_should_add_refuses_once_the_platform_hit_its_cap():
    assert should_add(_cand(), set(), 60, 60) is False


# --- запись ------------------------------------------------------------------

def test_the_lead_lands_in_the_main_tab():
    main, legacy = _main(), _legacy()

    assert SearchLeadsRepo(main, legacy, cap=60).add_new([_cand()]) == 1

    (row,) = main.appended
    assert _col(row, "Статус") == STATUS_NEW
    assert _col(row, "Источник") == "https://linkedin.com/jobs/view/1"


def test_the_candidates_tab_is_never_written_to_again():
    """Смысл всей правки: одна строка на вакансию, в одном месте."""
    main, legacy = _main(), _legacy()

    SearchLeadsRepo(main, legacy, cap=60).add_new([_cand()])

    assert legacy.appended == []


def test_a_url_already_a_lead_is_not_added_twice():
    main = _main([_lead_row("https://linkedin.com/jobs/view/1")])

    assert SearchLeadsRepo(main, _legacy(), cap=60).add_new([_cand()]) == 0
    assert main.appended == []


def test_a_vacancy_rejected_back_when_there_were_buttons_stays_rejected():
    """Отклонять больше нечем, поэтому память старой вкладки — единственное, что
    удерживает эти вакансии от возвращения."""
    legacy = _legacy([_cand_row("https://linkedin.com/jobs/view/1", status="rejected")])

    assert SearchLeadsRepo(_main(), legacy, cap=60).add_new([_cand()]) == 0


def test_the_cap_counts_leads_that_are_still_new():
    main = _main([_lead_row("https://linkedin.com/jobs/view/99")])

    added = SearchLeadsRepo(main, _legacy(), cap=1).add_new([_cand()])

    assert added == 0


def test_a_lead_already_sent_does_not_hold_a_slot():
    """Потолок бережёт от завала необработанным, а не считает историю."""
    main = _main([_lead_row("https://linkedin.com/jobs/view/99", status="sent")])

    assert SearchLeadsRepo(main, _legacy(), cap=1).add_new([_cand()]) == 1


def test_the_cap_is_per_platform():
    main = _main([_lead_row("https://linkedin.com/jobs/view/99", platform="linkedin")])
    repo = SearchLeadsRepo(main, _legacy(), cap=1)

    assert repo.add_new([_cand(url="https://remoteok.com/l/2", platform="remoteok")]) == 1


def test_two_finds_in_one_batch_do_not_share_an_id():
    main, repo = _main(), None
    repo = SearchLeadsRepo(main, _legacy(), cap=60)

    repo.add_new([_cand(url="https://linkedin.com/jobs/view/1"),
                  _cand(url="https://linkedin.com/jobs/view/2")])

    ids = [_col(r, "id") for r in main.appended]
    assert ids == [1, 2]


def test_known_urls_covers_both_tabs():
    main = _main([_lead_row("https://linkedin.com/jobs/view/1")])
    legacy = _legacy([_cand_row("https://remoteok.com/l/2")])

    known = SearchLeadsRepo(main, legacy, cap=60).known_urls()

    assert normalize_url("https://linkedin.com/jobs/view/1") in known
    assert normalize_url("https://remoteok.com/l/2") in known
