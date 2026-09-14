"""Страница, ушедшая на другой адрес прямо во время чтения, — не поломка отклика.

Живьём 2026-09-14 (лид #1214, Synapxe на SAP SuccessFactors): на странице
вакансии полей нет, `_reveal_apply_form` жмёт «Apply now »», сайт начинает
переход на страницу входа, а повторное чтение формы уже идёт — и `page.evaluate`
падает с «Execution context was destroyed, most likely because of a navigation».
Воспроизведено два раза из двух; лид уходил в `failed`, хотя страницу нужно было
просто дочитать после перехода.
"""
import pytest

from app.domain.page_observation import FieldObs, PageObservation
from app.infrastructure.channels import external_apply as ea

NAVIGATED = "Page.evaluate: Execution context was destroyed, most likely because of a navigation"

LOGIN = PageObservation(url="https://career.successfactors.com/career/login", fields=[
    FieldObs(tag="input", type="password", label="Password", ref="0"),
])


class _NavigatingPage:
    """Первые `fails` чтений падают с `error`, дальше отдаётся `obs`."""

    def __init__(self, fails: int, obs: PageObservation = LOGIN, error: str = NAVIGATED):
        self._fails = fails
        self._obs = obs
        self._error = error
        self.evaluations = 0
        self.waited = []

    def evaluate(self, js):
        self.evaluations += 1
        if self.evaluations <= self._fails:
            raise Exception(self._error)
        return ea.observation_to_raw(self._obs)

    def wait_for_load_state(self, state=None, timeout=None):
        self.waited.append(state)


def test_a_navigation_during_the_read_waits_for_the_new_page_and_reads_it():
    page = _NavigatingPage(fails=1)

    obs = ea.scrape_form(page)

    assert obs.url == "https://career.successfactors.com/career/login"
    assert page.waited == ["domcontentloaded"]


def test_a_page_that_never_settles_still_raises():
    """Повтор ограничен: страница, которая уходит без конца, не должна вешать прогон."""
    page = _NavigatingPage(fails=99)

    with pytest.raises(Exception, match="context was destroyed"):
        ea.scrape_form(page)
    assert page.evaluations <= 5


def test_other_errors_are_not_retried():
    """Закрытая вкладка — это не переход, ждать там нечего."""
    page = _NavigatingPage(fails=1, error="Target page, context or browser has been closed")

    with pytest.raises(Exception, match="has been closed"):
        ea.scrape_form(page)
    assert page.evaluations == 1
