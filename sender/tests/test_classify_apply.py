from app.application.classify_apply import classify
from app.domain.page_observation import FieldObs, PageObservation, Route


def _f(tag, **kw):
    return FieldObs(tag=tag, **kw)


def test_login_wall_is_gated():
    # A real login/registration wall is the only automatic skip.
    obs = PageObservation(url="https://x/apply/authentication", login_required=True,
                          fields=[_f("input", type="email", label="Email")])
    assert classify(obs) is Route.GATED


def test_invisible_captcha_form_is_not_gated():
    # reCAPTCHA presence must NOT skip a fillable form (invisible v3 is on almost
    # every ATS, incl. Comeet, and does not block filling/submitting).
    obs = PageObservation(
        url="https://www.comeet.co/jobs/x/apply",
        fields=[_f("input", type="email", label="Email", required=True),
                _f("input", type="text", label="First Name", required=True)],
        file_inputs=1, captcha=True)
    assert classify(obs) is Route.FORM


def test_lone_email_field_is_not_a_form():
    # A single "apply later" / subscribe email box (e.g. join.com listing page) is
    # not an application form -> not FORM.
    obs = PageObservation(url="https://join.com/companies/x",
                          fields=[_f("input", type="email", label="Email")],
                          apply_buttons=["Apply now", "Apply Later"])
    assert classify(obs) is Route.NONE


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
