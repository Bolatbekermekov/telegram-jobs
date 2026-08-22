"""Кнопка Easy Apply на верхней карточке против ссылок «похожих вакансий».

Лид #309 (вакансия 4456728594, QA Engineer в Seargin) ушёл в `manual` с заметкой
«нет ссылки внешнего отклика (возможно Easy Apply)». Замер живьём 2026-08-22
показал, что отклик у вакансии как раз Easy Apply — Voyager отдаёт
`ComplexOnsiteApply` и НЕ отдаёт `companyApplyUrl`, потому что внешнего отклика
у неё нет вовсе. То есть код ушёл не в ту ветку, а внешний путь потом честно
доложил, что ссылки нет.

Разметка на той же странице, после прогрузки ленты справа:

* верхняя карточка — `<button>Простая подача заявки</button>`, БЕЗ href;
* лента похожих вакансий — два `<a>` с тем же текстом в поддереве, у обоих
  href `https://www.linkedin.com/jobs/search-results/?keywords=`, где номера
  этой вакансии нет.

Итого селектор находит три элемента. Ни один href не называет нашу вакансию,
и старая проверка «сойдёт один-единственный контрол без href» требовала, чтобы
ОБЩИЙ счётчик равнялся единице. Он равнялся трём, и вакансия с рабочим Easy
Apply объявлялась внешней.

Считать надо не все совпадения, а совпадения БЕЗ href: элементы ленты href
несут всегда, а кнопка верхней карточки — никогда.
"""
from app.domain.channel import OutreachContent
from app.infrastructure.channels.linkedin import (
    SEL_APPLY_SUBMIT,
    SEL_EASY_APPLY,
    easy_apply_via_page,
)

JOB = "https://www.linkedin.com/jobs/view/4456728594/"
# Что несут ссылки ленты: номера вакансии в них нет ни у одной.
RAIL_HREF = "https://www.linkedin.com/jobs/search-results/?keywords="


class _Candidate:
    def __init__(self, page, selector, href):
        self._page = page
        self._selector = selector
        self.href = href

    def get_attribute(self, name):
        return self.href if name == "href" else None

    def evaluate(self, js, timeout=None):
        self._page.actions.append(("native-click", self._selector, self.href))

    def click(self, timeout=None):
        self._page.actions.append(("click", self._selector, self.href))

    def inner_text(self, timeout=None):
        return ""


class _FakeApplyPage:
    """Как `_FakeApplyPage` в test_job_url_slug, но каждый кандидат со СВОИМ
    href — иначе разницу между кнопкой карточки и лентой не выразить."""

    def __init__(self, hrefs):
        self._hrefs = hrefs          # что отдаёт SEL_EASY_APPLY по порядку
        self.actions = []
        self.url = ""

    def goto(self, url, **kw):
        self.actions.append(("goto", url))
        self.url = url

    def wait_for_load_state(self, state=None, timeout=None):
        pass

    def wait_for_timeout(self, ms):
        pass

    def locator(self, selector):
        page = self
        hrefs = self._hrefs if selector == SEL_EASY_APPLY else [None]
        count = len(hrefs) if selector in (SEL_EASY_APPLY, SEL_APPLY_SUBMIT) else 0

        class _Locator:
            def count(self_inner):
                return count

            def nth(self_inner, i):
                return _Candidate(page, selector, hrefs[i])

            @property
            def first(self_inner):
                return _Candidate(page, selector, hrefs[0])

            def inner_text(self_inner, timeout=None):
                return ""

        return _Locator()


def _clicked(page):
    return [a for a in page.actions if a[0] == "native-click"]


def test_the_top_card_button_wins_over_the_similar_jobs_rail():
    """Ровно разметка лида #309: кнопка без href плюс две ссылки ленты."""
    page = _FakeApplyPage([None, RAIL_HREF, RAIL_HREF])

    easy_apply_via_page(page, JOB, OutreachContent(body="привет"))

    # В поток вошли через кнопку верхней карточки, а не через ленту.
    assert ("native-click", SEL_EASY_APPLY, None) in page.actions
    assert not any(a[2] == RAIL_HREF for a in _clicked(page))
    # И дошли до отправки — то есть внешний путь не понадобился.
    assert ("native-click", SEL_APPLY_SUBMIT, None) in page.actions


def test_a_lone_button_still_works():
    """Прежний случай не должен сломаться: одна кнопка, ленты нет."""
    page = _FakeApplyPage([None])

    easy_apply_via_page(page, JOB, OutreachContent(body="привет"))

    assert ("native-click", SEL_EASY_APPLY, None) in page.actions


def test_two_caption_only_controls_are_still_refused():
    """Граница, ради которой проверка и заводилась: если контролов без href
    несколько, угадывать между ними нельзя — так прогон и уходил в чужую
    вакансию. Такая страница по-прежнему считается НЕ Easy Apply."""
    from app.infrastructure.channels.linkedin import _ExternalApplyNeeded
    import pytest

    page = _FakeApplyPage([None, None])

    with pytest.raises(_ExternalApplyNeeded):
        easy_apply_via_page(page, JOB, OutreachContent(body="привет"))

    assert not _clicked(page)
