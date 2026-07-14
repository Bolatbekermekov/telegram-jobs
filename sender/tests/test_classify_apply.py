from app.application.classify_apply import classify
from app.domain.page_observation import FieldObs, PageObservation, Route


def _f(tag, **kw):
    return FieldObs(tag=tag, **kw)


def test_join_com_gated_by_captcha():
    # Recon 2026-07-14: /apply/authentication had email + reCAPTCHA + "Continue with Google".
    obs = PageObservation(url="https://join.com/.../apply/authentication",
                          fields=[_f("input", type="email", label="Email")],
                          captcha=True)
    assert classify(obs) is Route.GATED


def test_ddrive_mailto_is_email():
    # Recon: no form, "Apply" = mailto:hr@ddrive.tech.
    obs = PageObservation(url="https://www.ddrive.tech/team/junior-software-developer",
                          mailto_links=["mailto:hr@ddrive.tech?subject=Junior"],
                          apply_buttons=["Join the team", "Apply"])
    assert classify(obs) is Route.EMAIL


def test_superplay_cookie_checkboxes_plus_comeet_iframe_is_iframe_ats():
    # Recon: visible fields were only cookie/consent checkboxes; real form in Comeet iframe.
    obs = PageObservation(
        url="https://www.superplay.co/careers-position/26.D66/",
        fields=[_f("input", type="checkbox", label="Performance Cookies"),
                _f("input", type="checkbox", label="checkbox label"),
                _f("input", type="text", label="Cookie list search")],
        iframes=["https://www.comeet.co/jobs/28.003/26.D66/apply?token=x&embedded=true"])
    assert classify(obs) is Route.IFRAME_ATS


def test_greenhouse_like_form():
    obs = PageObservation(
        url="https://boards.greenhouse.io/acme/jobs/1",
        fields=[_f("input", type="email", label="Email", required=True),
                _f("input", type="text", label="First Name", required=True)],
        file_inputs=1)
    assert classify(obs) is Route.FORM


def test_empty_page_is_none():
    assert classify(PageObservation(url="https://x.test")) is Route.NONE
