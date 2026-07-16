from app.domain.channel import ManualApplyRequired, OutreachContent
from app.infrastructure.channels import linkedin as li


class Loc:
    def __init__(self, n, text=""):
        self._n, self._text = n, text
        self.first = self

    def count(self):
        return self._n

    def inner_text(self, timeout=None):
        return self._text

    def click(self):
        pass


class JobPage:
    """Fake LinkedIn job page. `company_url` is what the Voyager fetch
    (page.evaluate) yields: a company apply URL for an offsite job, or None."""

    def __init__(self, company_url, easy_apply=False):
        self._company_url = company_url
        self._easy = easy_apply
        self.goto_urls = []
        self.eval_args = []

    def goto(self, url, wait_until=None):
        self.goto_urls.append(url)

    def locator(self, sel):
        if self._easy and "jobs-apply-button" in sel:
            return Loc(1)            # Easy Apply button present
        if "main" in sel:
            return Loc(1, "job description text")
        return Loc(0)

    def evaluate(self, js, arg=None):
        self.eval_args.append(arg)
        return self._company_url


def test_external_job_routes_to_external_apply_when_enabled():
    calls = {}

    def fake_external(page, job_url, content, **kw):
        calls["job_url"] = job_url

    ch = li.LinkedInChannel("state.json", headless=True,
                            external_apply_deps={"enabled": True, "fn": fake_external})
    ch._page = JobPage(company_url="https://company.example/apply")
    ch.send("https://www.linkedin.com/jobs/view/123", OutreachContent(body="hi"))
    assert calls["job_url"] == "https://www.linkedin.com/jobs/view/123"


def test_external_apply_disabled_raises_channel_error():
    ch = li.LinkedInChannel("state.json", headless=True,
                            external_apply_deps={"enabled": False, "fn": None})
    ch._page = JobPage(company_url=None)
    try:
        ch.send("https://www.linkedin.com/jobs/view/123", OutreachContent(body="hi"))
        assert False, "expected ChannelError"
    except li.ChannelError as exc:
        assert "внешний отклик" in str(exc)


def test_external_apply_navigates_to_company_url_then_calls_fn():
    """The fix: read companyApplyUrl from Voyager, navigate the page there, and
    hand THAT page (now the company site) to the external-apply fn."""
    calls = {}

    def fake_external(page, job_url, content, **kw):
        calls["page"] = page
        calls["job_url"] = job_url
        calls["ctx"] = kw.get("vacancy_context")

    page = JobPage(company_url="https://boards.greenhouse.io/acme/jobs/1")
    ch = li.LinkedInChannel("state.json", headless=True,
                            external_apply_deps={"enabled": True, "fn": fake_external})
    ch._page = page
    ch._external_apply("https://www.linkedin.com/jobs/view/123", OutreachContent(body="hi"))
    # navigated the page to the company's real apply URL...
    assert page.goto_urls[-1] == "https://boards.greenhouse.io/acme/jobs/1"
    # ...and handed that same (now-company) page to the fn, with the LinkedIn desc.
    assert calls["page"] is page
    assert calls["job_url"] == "https://www.linkedin.com/jobs/view/123"
    assert calls["ctx"] == "job description text"


def test_external_apply_no_company_url_raises_manual():
    """Not an offsite apply (Voyager yields nothing) -> manual; fn never called."""
    called = {"fn": False}

    def fake_external(page, job_url, content, **kw):
        called["fn"] = True

    page = JobPage(company_url=None)
    ch = li.LinkedInChannel("state.json", headless=True,
                            external_apply_deps={"enabled": True, "fn": fake_external})
    ch._page = page
    try:
        ch._external_apply("https://www.linkedin.com/jobs/view/123", OutreachContent(body="hi"))
        assert False, "expected ManualApplyRequired"
    except ManualApplyRequired as exc:
        assert "ручной отклик" in str(exc)
    assert called["fn"] is False
