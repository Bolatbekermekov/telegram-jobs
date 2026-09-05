"""Капча после отправки — заявка НЕ ушла, и говорить надо именно это.

Живьём 2026-09-05, лид #844 (Lever, вакансия Potloc). После «Submit» страница
показала hCaptcha; в сохранённом снимке (`unknown-jobs-lever-co-*.png`) она
занимает середину экрана поверх формы. Отчёт при этом сказал «ВОЗМОЖНО, ЗАЯВКА
УЖЕ УШЛА, проверь почту прежде чем откликаться повторно» — то есть отправил
владельца искать письмо, которого не будет.

Отличать по НАЛИЧИЮ рамки нельзя: невидимый reCAPTCHA v3 висит на половине форм
и ничему не мешает. Поэтому граница проходит по видимости и размеру.
"""
import pytest

from app.domain.channel import ManualApplyRequired
from app.domain.page_observation import FieldObs
from app.infrastructure.channels import external_apply as ea
from tests.test_submit_verification import _Page, ERR_SEL   # noqa: F401


class _Frame:
    def __init__(self, visible=True, w=400, h=570):
        self.visible, self.w, self.h = visible, w, h

    def is_visible(self, timeout=None):
        return self.visible

    def bounding_box(self):
        return {"width": self.w, "height": self.h}


class _CaptchaPage(_Page):
    """Страница, у которой на капчевом селекторе висит рамка заданного размера."""

    def __init__(self, frame, **kw):
        super().__init__(**kw)
        self.frame = frame

    def locator(self, sel):
        if sel == ea._CAPTCHA_SEL:
            frame = self.frame
            page = self

            class _L:
                def count(self):
                    return 0 if frame is None else 1

                def nth(self, i):
                    return frame
            return _L()
        return super().locator(sel)


URL = "https://jobs.lever.co/acme/1/apply"


def _page(frame):
    return _CaptchaPage(frame, text="Apply now", url=URL,
                        fields=[FieldObs(tag="input", label="Email", ref="0")])


def test_a_visible_challenge_says_the_application_did_not_go(monkeypatch):
    monkeypatch.setattr(ea, "_dump_form_debug", lambda *a, **k: None)
    with pytest.raises(ManualApplyRequired) as err:
        ea._verify_submitted(_page(_Frame()), URL)

    said = str(err.value)
    assert "капчу" in said
    assert "НЕ ушла" in said
    # И ни слова про почту: письма не будет.
    assert "почту" not in said


def test_an_invisible_v3_badge_is_not_a_captcha(monkeypatch):
    """reCAPTCHA v3 висит на половине форм и ничему не мешает. По ней каждая
    вторая заявка объявлялась бы заблокированной."""
    monkeypatch.setattr(ea, "_dump_form_debug", lambda *a, **k: None)
    with pytest.raises(ManualApplyRequired) as err:
        ea._verify_submitted(_page(_Frame(visible=False)), URL)
    assert "капчу" not in str(err.value)


def test_a_tiny_badge_is_not_a_captcha(monkeypatch):
    """Значок 70×60 виден, но ничего не загораживает."""
    monkeypatch.setattr(ea, "_dump_form_debug", lambda *a, **k: None)
    with pytest.raises(ManualApplyRequired) as err:
        ea._verify_submitted(_page(_Frame(w=70, h=60)), URL)
    assert "капчу" not in str(err.value)


def test_no_captcha_frame_at_all_keeps_the_old_outcome(monkeypatch):
    monkeypatch.setattr(ea, "_dump_form_debug", lambda *a, **k: None)
    with pytest.raises(ManualApplyRequired) as err:
        ea._verify_submitted(_page(None), URL)
    assert "ВОЗМОЖНО, ЗАЯВКА УЖЕ УШЛА" in str(err.value)
