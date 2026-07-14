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


class PopupPage:
    """The new browser tab LinkedIn opens for an external-apply job (the company
    site). Distinct object so the test can assert it — not the original page — is
    the one handed to the external-apply fn."""


class ExpectPageCtx:
    """Mimics playwright's context.expect_page() context manager: `.value` yields
    the popup page after the block runs."""
    def __init__(self, popup):
        self.value = popup

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class Ctx:
    def __init__(self, popup):
        self._popup = popup

    def expect_page(self, timeout=None):
        return ExpectPageCtx(self._popup)


class ExtLoc:
    def __init__(self, n, text=""):
        self._n = n
        self._text = text
        self.first = self

    def count(self):
        return self._n

    def inner_text(self, timeout=None):
        return self._text

    def click(self):
        pass


class JobPageWithPopup:
    """External-apply job page: the external-apply button is present and clicking
    it opens a new tab, surfaced via context.expect_page()."""
    def __init__(self, popup):
        self.context = Ctx(popup)

    def goto(self, url, wait_until=None):
        pass

    def locator(self, sel):
        if sel == li.SEL_EXTERNAL_APPLY:
            return ExtLoc(1)
        if "jobs-description" in sel:
            return ExtLoc(1, "job description text")
        return ExtLoc(0)


def test_external_apply_hands_popup_page_to_fn():
    calls = {}

    def fake_external(page, job_url, content, **kw):
        calls["page"] = page
        calls["job_url"] = job_url

    popup = PopupPage()
    ch = li.LinkedInChannel("state.json", headless=True,
                            external_apply_deps={"enabled": True, "fn": fake_external})
    ch._page = JobPageWithPopup(popup)
    ch._external_apply("https://www.linkedin.com/jobs/view/123", OutreachContent(body="hi"))
    # The fn must receive the POPUP tab (company site), not the original job page.
    assert calls["page"] is popup
    assert calls["job_url"] == "https://www.linkedin.com/jobs/view/123"
