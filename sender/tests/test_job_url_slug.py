"""LinkedIn job URLs in their share form — `/jobs/view/<slug>-<id>/`.

Lead #169 (2026-07-30) was an ordinary Easy Apply vacancy that ended up `manual`
with «нет ссылки внешнего отклика (возможно Easy Apply)». Measured live on the
same URL: the page carries the real entry point
(«Простая подача заявки», href `/jobs/view/4425082337/apply/?openSDUIApplyFlow=true`),
and `SEL_EASY_APPLY` matched it — but `_job_id` answered "" for
`/jobs/view/staff-backend-software-engineer-at-enhesa-4425082337/`, because its
pattern demanded digits directly after `/jobs/view/`. With no id:

* `_open_apply_flow` can never confirm an entry point belongs to this job
  (`job_id in href` is skipped on a falsy id), so it fell through to external apply;
* the Voyager lookup, which carried a copy of the same pattern, returned null;
* and `_still_on_the_job` — the guard that stops the walk from paging through
  somebody else's vacancies — answers True unconditionally on an empty id.

Three of the sheet's 53 job leads use this form (37, 40, 169).
"""
from app.infrastructure.channels.linkedin import (
    SEL_APPLY_SUBMIT,
    SEL_EASY_APPLY,
    _JOB_ID_PATTERN,
    _job_id,
    _still_on_the_job,
    _VOYAGER_APPLY_JS,
    easy_apply_via_page,
)
from app.domain.channel import OutreachContent
from app.infrastructure.vacancy_fetcher import is_linkedin_job_url

SLUG_JOB = ("https://www.linkedin.com/jobs/view/"
            "staff-backend-software-engineer-at-enhesa-4425082337/")


def test_plain_numeric_job_url_still_parses():
    assert _job_id("https://www.linkedin.com/jobs/view/4425082337/") == "4425082337"
    assert _job_id("https://www.linkedin.com/jobs/view/4425082337") == "4425082337"


def test_slug_job_url_parses():
    assert _job_id(SLUG_JOB) == "4425082337"


def test_apply_and_query_forms_parse():
    assert _job_id("https://www.linkedin.com/jobs/view/4425082337/apply/"
                   "?openSDUIApplyFlow=true&trackingId=x") == "4425082337"
    assert _job_id("https://www.linkedin.com/jobs/view/4425082337?refId=abc") == "4425082337"


def test_digits_inside_the_slug_are_not_mistaken_for_the_id():
    """A slug carries its own numbers («python-3-developer»); the id is the run of
    digits that ENDS the segment, which is why the pattern anchors on what follows."""
    assert _job_id("https://www.linkedin.com/jobs/view/"
                   "senior-python-3-developer-at-acme-1234567/") == "1234567"


def test_a_slug_with_no_id_is_still_no_id():
    assert _job_id("https://www.linkedin.com/jobs/view/some-slug-without-an-id/") == ""
    assert _job_id("https://www.linkedin.com/in/someone/") == ""


def test_voyager_lookup_uses_the_same_pattern():
    """The apply-url lookup runs the pattern in the page, and it drifting apart
    from the Python one is exactly how lead #169 failed twice over."""
    assert _JOB_ID_PATTERN in _VOYAGER_APPLY_JS.replace("\\\\", "\\")


def test_the_still_on_the_job_guard_works_for_slug_urls():
    job_id = _job_id(SLUG_JOB)

    class _P:
        url = "https://www.linkedin.com/jobs/search-results/?currentJobId=999&start=200"

    assert _still_on_the_job(_P(), job_id) is False


def test_slug_job_url_is_fetchable_for_the_vacancy_re_read():
    """The re-read that fills an empty «Вакансия» column keys on the same shape."""
    assert is_linkedin_job_url(SLUG_JOB)
    assert is_linkedin_job_url("https://www.linkedin.com/jobs/view/4425082337/")
    assert not is_linkedin_job_url("https://www.linkedin.com/in/someone/")


class _FakeApplyPage:
    """Enough Page to drive _open_apply_flow: one Easy Apply anchor whose href
    carries the numeric id, exactly as the live page serves it."""

    def __init__(self, counts, href):
        self._counts = counts
        self._href = href
        self.actions = []
        self.url = ""

    def goto(self, url, **kw):
        self.actions.append(("goto", url))
        self.url = url

    def wait_for_load_state(self, state=None, timeout=None):
        pass

    def wait_for_timeout(self, ms):
        pass

    def locator(self, selector):
        page = self

        class _Locator:
            def count(self_inner):
                return page._counts.get(selector, 0)

            @property
            def first(self_inner):
                return self_inner

            def nth(self_inner, i):
                return self_inner

            def get_attribute(self_inner, name):
                return page._href if name == "href" else None

            def click(self_inner, timeout=None):
                page.actions.append(("click", selector))

            def evaluate(self_inner, js, timeout=None):
                page.actions.append(("native-click", selector))

            def inner_text(self_inner, timeout=None):
                return ""

        return _Locator()


def test_easy_apply_enters_the_flow_from_a_slug_job_url():
    """The regression itself: the entry point is there and names this job in its
    href, so the walk must follow it instead of falling out to external apply."""
    apply_href = ("https://www.linkedin.com/jobs/view/4425082337/apply/"
                  "?openSDUIApplyFlow=true&trackingId=AwdMI")
    page = _FakeApplyPage({SEL_EASY_APPLY: 4, SEL_APPLY_SUBMIT: 1}, href=apply_href)

    easy_apply_via_page(page, SLUG_JOB, OutreachContent(body="hi"))

    assert ("goto", apply_href) in page.actions
    assert ("native-click", SEL_APPLY_SUBMIT) in page.actions
