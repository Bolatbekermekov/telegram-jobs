from app.domain.channel import OutreachContent
from app.infrastructure.channels import linkedin as li


class Loc:
    def __init__(self, n):
        self._n = n
        self.first = self

    def count(self):
        return self._n

    def click(self):
        pass


class Page:
    def __init__(self, has_easy_apply):
        self._has = has_easy_apply

    def goto(self, url, wait_until=None):
        pass

    def locator(self, sel):
        # No Easy Apply button => external-apply job.
        return Loc(1 if (self._has and "jobs-apply-button" in sel) else 0)


def test_external_job_calls_external_apply_when_enabled():
    calls = {}

    def fake_external(page, job_url, content, **kw):
        calls["job_url"] = job_url

    ch = li.LinkedInChannel("state.json", headless=True,
                            external_apply_deps={"enabled": True, "fn": fake_external})
    ch._page = Page(has_easy_apply=False)
    ch.send("https://www.linkedin.com/jobs/view/123", OutreachContent(body="hi"))
    assert calls["job_url"] == "https://www.linkedin.com/jobs/view/123"


def test_external_job_raises_when_disabled():
    ch = li.LinkedInChannel("state.json", headless=True,
                            external_apply_deps={"enabled": False, "fn": None})
    ch._page = Page(has_easy_apply=False)
    try:
        ch.send("https://www.linkedin.com/jobs/view/123", OutreachContent(body="hi"))
        assert False, "expected ChannelError"
    except li.ChannelError as exc:
        assert "внешний отклик" in str(exc)
