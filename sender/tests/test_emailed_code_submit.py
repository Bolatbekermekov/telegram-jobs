"""Экран «введите 8-значный код из письма» Greenhouse — код вводится и заявка уходит.

Разметка снята с живой страницы (дамп job-boards.greenhouse.io, 2026-09):
`fieldset#email-verification`, восемь полей `#security-input-0..7` с
`maxlength=1`, подпись «Security code», повторная отправка — та же кнопка
«Submit application».
"""
import pytest

from app.domain.channel import ManualApplyRequired
from app.infrastructure.channels import external_apply as ea


class _Cell:
    def __init__(self, page, i):
        self.page, self.i = page, i

    def fill(self, value, timeout=None):
        self.page.cells[self.i] = value[:1]


class _Cells:
    def __init__(self, page):
        self.page = page

    def count(self):
        return len(self.page.cells)

    def nth(self, i):
        return _Cell(self.page, i)

    @property
    def first(self):
        return _Cell(self.page, 0)

    def evaluate_all(self, js):
        return "".join(self.page.cells)


class _Page:
    def __init__(self, n=8):
        self.cells = [""] * n

    def locator(self, sel):
        assert "security-input" in sel
        return _Cells(self)


def test_the_code_goes_one_character_per_cell():
    page = _Page()
    assert ea._enter_emailed_code(page, "Ab3dEf9h") is True
    assert page.cells == list("Ab3dEf9h")


def test_no_code_cells_means_nothing_is_entered():
    page = _Page(n=0)
    assert ea._enter_emailed_code(page, "Ab3dEf9h") is False


# --- ветка в проверке отправки ---

@pytest.fixture
def _screen(monkeypatch):
    """Страница после «Submit»: сначала просит код, после повторной отправки — спасибо."""
    state = {"entered": None, "resubmits": 0}
    monkeypatch.setattr(ea, "_VERIFY_ATTEMPTS", 1)
    monkeypatch.setattr(ea, "_page_text", lambda page: (
        "Thank you for applying! Your application has been received."
        if state["resubmits"] else
        "A verification code was sent to me@gmail.com. To submit your application, "
        "enter the 8-character code to confirm you're a human. Security code"))
    monkeypatch.setattr(ea, "scrape_form", lambda page: type("O", (), {"fields": [1]})())
    monkeypatch.setattr(ea, "_captcha_blocking", lambda page: False)
    monkeypatch.setattr(ea, "_dump_form_debug", lambda page, tag: None)
    monkeypatch.setattr(ea, "_enter_emailed_code",
                        lambda page, code: state.__setitem__("entered", code) or True)
    monkeypatch.setattr(ea, "_resubmit", lambda page: state.__setitem__(
        "resubmits", state["resubmits"] + 1))
    return state


def test_with_a_mailbox_the_code_is_entered_and_the_application_goes(_screen):
    asked = []
    ea._verify_submitted(object(), "https://job-boards.greenhouse.io/x/jobs/1",
                         code_source=lambda since: asked.append(since) or "Ab3dEf9h",
                         since=123.0)
    assert asked == [123.0], "код ищется в письмах, пришедших после нажатия «Отправить»"
    assert _screen["entered"] == "Ab3dEf9h" and _screen["resubmits"] == 1


def test_without_a_mailbox_it_is_a_manual_apply_as_before(_screen):
    with pytest.raises(ManualApplyRequired, match="код подтверждения"):
        ea._verify_submitted(object(), "https://job-boards.greenhouse.io/x/jobs/1")


def test_a_code_that_never_arrived_says_so(_screen):
    with pytest.raises(ManualApplyRequired, match="не пришёл"):
        ea._verify_submitted(object(), "https://job-boards.greenhouse.io/x/jobs/1",
                             code_source=lambda since: "", since=1.0)
    assert _screen["resubmits"] == 0
