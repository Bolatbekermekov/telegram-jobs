"""После подтверждения «вакансия в другой стране» окно отклика надо дождаться.

Живьём 2026-09-14 (лиды #1263 и #1265, первый прогон с резюме под роли): на
вакансию из России hh сначала спрашивает согласие показать резюме в другой
стране, и только после него открывает окно отклика с выбором резюме и
сопроводительным. Пока резюме было одно, после согласия hh откликался сразу,
и фиксированной паузы в 2,5 с хватало. Теперь окно приходит позже паузы, бот не
видел поля письма, перезагружал страницу и писал «поле письма не появилось».
"""
import app.infrastructure.channels.headhunter as hh
from app.domain.channel import OutreachContent
from tests.test_headhunter_channel import _FakePage

POPUP = (hh.SEL_LETTER_TOGGLE, hh.SEL_LETTER_INPUT, hh.SEL_SUBMIT)


class _SlowPopupPage(_FakePage):
    """Окно отклика появляется, только если его ДОЖДАТЬСЯ после согласия."""

    def __init__(self):
        super().__init__({hh.SEL_APPLY: 1, hh.SEL_COUNTRY_CONFIRM: 1})
        self.confirmed = False

    def wait_for_selector(self, selector, **kw):
        super().wait_for_selector(selector, **kw)
        if self.confirmed and any(part in selector for part in POPUP):
            for key in POPUP:
                self._counts[key] = 1

    def locator(self, selector):
        loc = super().locator(selector)
        page = self
        if selector == hh.SEL_COUNTRY_CONFIRM:
            original = loc.click

            def click(timeout=None):
                original(timeout)
                page.confirmed = True
                page._counts[hh.SEL_COUNTRY_CONFIRM] = 0

            loc.click = click
        return loc


def test_the_response_window_is_awaited_after_the_country_consent(monkeypatch):
    monkeypatch.setattr(hh, "_verify_submitted", lambda page, debug_dir=None: None)
    page = _SlowPopupPage()

    hh.apply_via_page(page, "https://hh.ru/vacancy/137171893", OutreachContent(body="letter"))

    assert ("fill", hh.SEL_LETTER_INPUT, "letter") in page.actions
    assert ("click", hh.SEL_SUBMIT) in page.actions
