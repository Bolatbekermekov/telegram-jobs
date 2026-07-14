import pytest

from app.application.auto_apply import build_plan
from app.domain.apply_profile import ApplyProfile
from app.domain.channel import ManualApplyRequired, OutreachContent
from app.domain.page_observation import FieldObs, PageObservation
from app.infrastructure.channels import external_apply as ea

PROF = ApplyProfile(full_name="B Y", email="a@b.com")


class FakeLocator:
    def __init__(self, page, sel):
        self.page = page
        self.sel = sel
        self.first = self

    def count(self):
        return 1 if self.sel in self.page.present else 0

    def click(self):
        self.page.clicks.append(self.sel)

    def fill(self, v):
        self.page.filled[self.sel] = v

    def set_input_files(self, v):
        self.page.filled[self.sel] = ("file", v)

    def select_option(self, index):
        self.page.filled[self.sel] = ("choice", index)

    def check(self):
        self.page.filled[self.sel] = ("check", True)


class FakePage:
    def __init__(self, obs, present=()):
        self._obs = obs
        self.present = set(present) | {f'[data-af="{f.ref}"]' for f in obs.fields}
        self.clicks = []
        self.filled = {}

    def evaluate(self, js):        # scrape_form calls page.evaluate(_SCRAPE_JS)
        return ea.observation_to_raw(self._obs)

    def locator(self, sel):
        return FakeLocator(self, sel)


def _obs_form():
    return PageObservation(url="https://boards.greenhouse.io/x/jobs/1", fields=[
        FieldObs(tag="input", type="email", label="Email", required=True, ref="0"),
        FieldObs(tag="input", type="file", label="Resume", required=True, ref="1"),
    ])


def test_form_route_fills_and_submits():
    page = FakePage(_obs_form(), present=[ea.SEL_SUBMIT])
    ea.external_apply(page, "https://job", OutreachContent(body="hi"), PROF, "C:/cv.pdf")
    assert page.filled['[data-af="0"]'] == "a@b.com"
    assert page.filled['[data-af="1"]'] == ("file", "C:/cv.pdf")
    assert ea.SEL_SUBMIT in page.clicks


def test_dry_run_fills_but_does_not_submit():
    page = FakePage(_obs_form(), present=[ea.SEL_SUBMIT])
    with pytest.raises(ManualApplyRequired, match="DRY_RUN"):
        ea.external_apply(page, "https://job", OutreachContent(body="hi"), PROF,
                          "C:/cv.pdf", dry_run=True)
    assert ea.SEL_SUBMIT not in page.clicks
    assert page.filled['[data-af="0"]'] == "a@b.com"


def test_gated_page_raises_manual():
    page = FakePage(PageObservation(url="https://join.com/apply/authentication",
                                    captcha=True))
    with pytest.raises(ManualApplyRequired, match="гейт"):
        ea.external_apply(page, "https://job", OutreachContent(body="hi"), PROF, "C:/cv.pdf")


def test_unmapped_required_raises_manual_before_submit():
    obs = PageObservation(url="https://x", fields=[
        FieldObs(tag="input", type="text", label="Mystery required experience",
                 required=True, ref="0")])
    page = FakePage(obs, present=[ea.SEL_SUBMIT])
    # free-text field (routes to FORM), maps to AI but no answerer -> stays empty
    # -> required-unfilled -> manual  (brief said "code"; committed classifier needs
    #  an apply-hint word to route a lone field to FORM, hence "experience")
    with pytest.raises(ManualApplyRequired, match="обязательные"):
        ea.external_apply(page, "https://job", OutreachContent(body="hi"), PROF, "C:/cv.pdf")
    assert ea.SEL_SUBMIT not in page.clicks


def _obs_mailto():
    return PageObservation(url="https://ddrive.tech/team/junior",
                           mailto_links=["mailto:hr@ddrive.tech?subject=Junior%20Dev"],
                           apply_buttons=["Apply"])


class RecordingEmail:
    def __init__(self):
        self.sent = []

    def start(self): pass
    def stop(self): pass

    def send(self, target, content):
        self.sent.append((target, content.subject, content.attachment_path))


def test_email_route_sends_via_email_channel():
    page = FakePage(_obs_mailto())
    mail = RecordingEmail()
    ea.external_apply(page, "https://job", OutreachContent(body="cover letter"),
                      PROF, "C:/cv.pdf", email_channel=mail,
                      subject_maker=lambda ctx: "Application: Junior Dev",
                      vacancy_context="JOB")
    assert mail.sent == [("hr@ddrive.tech", "Application: Junior Dev", "C:/cv.pdf")]


def test_email_route_without_channel_raises_manual():
    page = FakePage(_obs_mailto())
    with pytest.raises(ManualApplyRequired, match="email"):
        ea.external_apply(page, "https://job", OutreachContent(body="x"), PROF, "C:/cv.pdf")


class NavFakePage(FakePage):
    """Fake page whose observation changes after goto() (iframe src -> real form)."""
    def __init__(self, first_obs, after_goto_obs):
        super().__init__(first_obs)
        self._after = after_goto_obs
        self.goto_url = None

    def goto(self, url, wait_until=None):
        self.goto_url = url
        self._obs = self._after
        self.present |= {f'[data-af="{f.ref}"]' for f in self._after.fields}


def test_iframe_ats_navigates_into_frame_then_fills():
    comeet = "https://www.comeet.co/jobs/28/26/apply?token=x&embedded=true"
    first = PageObservation(url="https://superplay.co/careers/1", iframes=[comeet],
                            fields=[FieldObs(tag="input", type="checkbox",
                                             label="Functional Cookies", ref="0")])
    inner = PageObservation(url=comeet, fields=[
        FieldObs(tag="input", type="email", label="Email", required=True, ref="0")],
        file_inputs=1)
    page = NavFakePage(first, inner)
    page.present.add(ea.SEL_SUBMIT)
    ea.external_apply(page, "https://job", OutreachContent(body="hi"), PROF, "C:/cv.pdf")
    assert page.goto_url == comeet
    assert page.filled['[data-af="0"]'] == "a@b.com"
    assert ea.SEL_SUBMIT in page.clicks
