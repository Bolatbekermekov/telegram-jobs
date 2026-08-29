from app.infrastructure.search.wellfound_search import build_jobs_url, parse_job_cards, role_slug


def test_build_jobs_url_contains_query():
    url = build_jobs_url("junior")
    assert "wellfound.com" in url and "junior" in url


class _FakeCard:
    def __init__(self, d):
        self._d = d

    def get_text(self, role):
        return self._d.get(role, "")

    def get_href(self):
        return self._d["href"]


def test_parse_job_cards_keeps_salary():
    cards = [_FakeCard({"title": "Junior Dev", "company": "Acme", "salary": "$40k–55k",
                        "location": "Remote", "href": "https://wellfound.com/jobs/9"})]
    out = parse_job_cards(cards, limit=10)
    c = out[0]
    assert c.platform == "wellfound" and c.kind == "job"
    assert c.salary == "$40k–55k" and c.company == "Acme"
    assert c.url == "https://wellfound.com/jobs/9"


def test_parse_job_cards_blank_salary_ok():
    cards = [_FakeCard({"title": "t", "company": "c", "salary": "",
                        "location": "Remote", "href": "https://wellfound.com/jobs/1"})]
    assert parse_job_cards(cards, limit=10)[0].salary == ""


def test_parse_respects_limit():
    cards = [_FakeCard({"title": "t", "company": "c", "salary": "", "location": "x",
                        "href": f"https://wellfound.com/jobs/{i}"}) for i in range(4)]
    assert len(parse_job_cards(cards, limit=2)) == 2


# --- условия найма: то, что решает, примет ли площадка заявку ---------------
#
# Замер живой страницы 2026-08-02 (wellfound.com/jobs/4372312-software-engineer):
# `describe()` открывает страницу вакансии, но возвращает только элемент с
# классом `description`, а блок условий лежит ВНЕ него. Проверено на месте:
#   элемент description найден, 3224 символа
#   содержит «Hires remotely in»  -> НЕТ
#   содержит «Visa Sponsorship»   -> НЕТ
# Поэтому скорер видел «Remote only», ставил 82/100 и ничего не знал про девять
# разрешённых стран. Несовпадение вскрывалось только на отклике.

_REAL_PAGE = """Software Engineer
$110k – $140k • No equity
Reposted: 2 weeks ago• Recruiter recently active
Hires remotely in
Argentina -
Australia -
Brazil -
Canada -
China -
India -
Japan -
United States -
South Korea
Preferred Timezones
Pacific Time
Relocation
Allowed
Skills
TypeScript
Visa Sponsorship
Not Available
Company Location
Los Angeles
Remote Work Policy
Remote only
"""


def test_eligibility_block_keeps_the_country_allowlist():
    from app.infrastructure.search.wellfound_search import eligibility_block
    got = eligibility_block(_REAL_PAGE)
    for country in ("Argentina", "United States", "South Korea"):
        assert country in got, country
    assert "Hires remotely in" in got


def test_eligibility_block_keeps_visa_and_relocation():
    """Именно эта пара решает, есть ли путь при готовности переехать."""
    from app.infrastructure.search.wellfound_search import eligibility_block
    got = eligibility_block(_REAL_PAGE)
    assert "Visa Sponsorship" in got and "Not Available" in got
    assert "Relocation" in got and "Allowed" in got


def test_eligibility_block_keeps_remote_policy_and_timezone():
    from app.infrastructure.search.wellfound_search import eligibility_block
    got = eligibility_block(_REAL_PAGE)
    assert "Remote only" in got
    assert "Pacific Time" in got


def test_eligibility_block_drops_the_noise():
    """Блок идёт в промпт скорера — лишние строки там платные."""
    from app.infrastructure.search.wellfound_search import eligibility_block
    got = eligibility_block(_REAL_PAGE)
    assert "Reposted" not in got
    assert "TypeScript" not in got          # секция Skills — не про допуск
    assert len(got) < 400


def test_eligibility_block_is_empty_when_the_page_has_no_such_fields():
    from app.infrastructure.search.wellfound_search import eligibility_block
    assert eligibility_block("Just a job description with no eligibility fields.") == ""
    assert eligibility_block("") == ""


# --- адрес выдачи: страница роли, а не /jobs?q= -------------------------------
#
# Замер 2026-08-29: `/jobs` не слышит НИ ОДНОГО параметра запроса. `?q=`,
# `?keywords=`, `job_search[keywords]` и `&page=2` дают побайтно один набор —
# 17 вакансий, счётчик «192 results», — и это сохранённый поиск владельца, а не
# наша выдача. Три разных слова дали пересечение 17 из 17.

def test_search_url_is_a_role_page_not_a_query():
    url = build_jobs_url("golang developer")
    assert url == "https://wellfound.com/role/golang-developer"
    assert "?q=" not in url


def test_remote_only_uses_the_narrower_role_page():
    """`/role/r/<slug>` — подмножество: 26 против 56, пересечение 17."""
    assert build_jobs_url("golang developer", True) == \
        "https://wellfound.com/role/r/golang-developer"


def test_page_number_reaches_the_url():
    assert build_jobs_url("golang developer", False, 3) == \
        "https://wellfound.com/role/golang-developer?page=3"


def test_first_page_has_no_page_parameter():
    assert build_jobs_url("golang developer", False, 1).endswith("golang-developer")


def test_slug_is_measured_not_guessed_where_the_page_does_not_exist():
    """Страниц nodejs-developer, nextjs-developer и llm-engineer у Wellfound нет."""
    assert role_slug("node.js developer") == "node-js-developer"
    assert role_slug("next.js developer") == "javascript-developer"
    assert role_slug("llm engineer") == "machine-learning-engineer"


def test_slug_falls_back_to_plain_kebab_for_unmapped_words():
    assert role_slug("Golang Developer") == "golang-developer"
    assert role_slug("qa automation engineer") == "qa-automation-engineer"
    assert role_slug("  python   developer  ") == "python-developer"


def test_two_words_can_share_one_role_page():
    """Не ошибка таблицы, а свойство справочника Wellfound."""
    assert role_slug("react native developer") == role_slug("mobile developer")
