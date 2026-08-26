"""Кнопка отклика увела на юридический текст — это надо называть своим именем.

Замер живьём 2026-08-26 на лидах #412 и #413 (Zalando). У них стоит Usercentrics,
и он рисуется в shadow DOM — поэтому согласие мы не видим и не отвечаем на него.
Кнопка «Apply» без ответа на согласие уводит на
`corporate.zalando.com/en/zalando-data-protection-statement`, где формы нет
вовсе и пути дальше тоже нет (проверено: ни одной кнопки continue/apply).

В таблицу при этом попадало «форма не распознана: <адрес политики>». Формально
верно, а по смыслу — ложный след: выглядит как поломка разбора формы, хотя на
самом деле нас увели с вакансии на юридический документ.
"""
from app.domain.legal_page import looks_like_legal_page


def test_zalando_data_protection_statement():
    assert looks_like_legal_page(
        "https://corporate.zalando.com/en/zalando-data-protection-statement") is True


def test_common_legal_paths():
    for url in ("https://acme.com/privacy-policy",
                "https://acme.com/en/terms-of-service",
                "https://acme.com/impressum",
                "https://acme.com/de/datenschutz",
                "https://acme.com/cookie-policy",
                "https://acme.com/legal/gdpr"):
        assert looks_like_legal_page(url) is True, url


def test_job_pages_are_not_legal_pages():
    for url in ("https://jobs.zalando.com/en/jobs/2723788-Principal-Software-Engineer",
                "https://careers.bluethrone.io/jobs/8175038-senior-backend-engineer-golang",
                "https://job-boards.greenhouse.io/embed/job_app?for=n26&token=7925103"):
        assert looks_like_legal_page(url) is False, url


def test_a_vacancy_about_privacy_is_not_a_legal_page():
    # Вакансия «Privacy Engineer» — это работа, а не политика. Раньше правило по
    # подстроке отправило бы такой лид в ручной отклик ни за что.
    assert looks_like_legal_page(
        "https://acme.com/careers/privacy-engineer") is False
    assert looks_like_legal_page(
        "https://acme.com/jobs/data-protection-officer") is False


def test_blank_and_garbage():
    assert looks_like_legal_page("") is False
    assert looks_like_legal_page(None) is False


# --- проводка в канал -------------------------------------------------------

import pytest                                                       # noqa: E402

from app.domain.apply_profile import ApplyProfile                   # noqa: E402
from app.domain.channel import ManualApplyRequired, OutreachContent  # noqa: E402
from app.domain.page_observation import PageObservation             # noqa: E402
from app.infrastructure.channels import external_apply as ea        # noqa: E402

JOB_URL = "https://jobs.zalando.com/en/jobs/2723788-Principal-Software-Engineer"
LEGAL_URL = "https://corporate.zalando.com/en/zalando-data-protection-statement"


class _Loc:
    def __init__(self, page):
        self._page = page

    def count(self):
        return 1

    def nth(self, i):
        return self

    def is_visible(self):
        return True

    def scroll_into_view_if_needed(self, timeout=None):
        pass

    def click(self, timeout=None, force=False):
        self._page.url = LEGAL_URL      # ровно то, что делает кнопка Zalando


class _Page:
    """Страница вакансии без формы, чья кнопка «Apply» уводит на политику."""

    def __init__(self):
        self.url = JOB_URL

    def evaluate(self, js, *a):
        return ea.observation_to_raw(PageObservation(url=self.url, fields=[]))

    def locator(self, sel):
        return _Loc(self)

    def wait_for_timeout(self, ms):
        pass


def test_reveal_landing_on_a_legal_page_names_the_reason_and_the_job_url():
    page = _Page()
    with pytest.raises(ManualApplyRequired) as exc:
        ea.external_apply(page, JOB_URL, OutreachContent(body="hi"),
                          ApplyProfile(email="a@b.com"), "/cv.pdf")
    message = str(exc.value)
    assert "юридический текст" in message
    assert JOB_URL in message           # человеку нужен адрес вакансии...
    assert LEGAL_URL not in message     # ...а не адрес политики
