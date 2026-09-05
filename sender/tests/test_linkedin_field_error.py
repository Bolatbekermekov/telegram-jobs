"""Ошибка поля Easy Apply, которая лежит НЕ в `role=alert`.

Живьём 2026-09-05, вакансия 4461771754 (дамп `easyapply-steps-4461771754`).
Экран скрининговых вопросов показывал «Недопустимое значение» под двумя полями,
`role=alert` на странице не было НИ ОДНОГО, и обход шесть раз подряд жал «Далее»
по одному и тому же экрану, а потом сдался с «не дошёл за 8 шагов».

Разметка снята с дампа: текст ошибки и счётчик символов лежат в подсказке, на
которую поле ссылается через `aria-describedby`. Классы заменены на говорящие,
всё остальное как на странице.
"""
import pytest

from app.infrastructure.channels.linkedin import _first_alert_text, _first_field_error


@pytest.fixture(scope="module")
def page():
    pw = pytest.importorskip("patchright.sync_api")
    try:
        p = pw.sync_playwright().start()
        browser = p.chromium.launch(headless=True, channel="chrome")
    except Exception as exc:  # noqa: BLE001 — без Chrome тест не запускается
        pytest.skip(f"нет браузера: {type(exc).__name__}")
    pg = browser.new_context().new_page()
    yield pg
    browser.close()
    p.stop()


def show(page, html):
    page.set_content(f"<body>{html}</body>")


_SALARY = """
  <input required id="q-salary" aria-describedby="q-salary-info"
         aria-label="What is your current salary ?" type="text"
         value="Не готов раскрывать текущую зарплату.">
  <div id="q-salary-info">Недопустимое значение 37/20 Использовано: 37 из 20 символов</div>
"""
_YEARS = """
  <input required id="q-js" aria-describedby="q-js-info"
         aria-label="How many years of work experience do you have with JavaScript?"
         type="text" value="3">
  <div id="q-js-info">1/20 Использовано: 1 из 20 символов</div>
"""


def test_the_field_error_is_found_and_names_the_field(page):
    show(page, _YEARS + _SALARY)

    # Прежняя проверка на этой странице молчит — ровно поэтому обход и зациклился.
    assert _first_alert_text(page) == ""

    said = _first_field_error(page)
    assert "current salary" in said
    assert "Недопустимое значение" in said
    # Счётчик тоже уезжает в заметку: без него «недопустимое» не говорит, чем.
    assert "20 символов" in said


def test_a_healthy_counter_is_not_an_error(page):
    """«Использовано: 1 из 20 символов» — норма, а не жалоба. Иначе каждый
    заполненный экран читался бы как отказ и обход вставал бы на первом же."""
    show(page, _YEARS)
    assert _first_field_error(page) == ""


def test_english_wording_counts_too(page):
    show(page, """
      <input required id="e" aria-describedby="e-info" aria-label="Notice period" value="soon">
      <div id="e-info">Invalid value</div>
    """)
    assert "Notice period" in _first_field_error(page)


def test_several_bad_fields_are_all_named(page):
    show(page, _SALARY + """
      <input required id="q-notice" aria-describedby="q-notice-info"
             aria-label="What is your notice period (in weeks)?" value="1 month">
      <div id="q-notice-info">Недопустимое значение 7/20 Использовано: 7 из 20 символов</div>
    """)
    said = _first_field_error(page)
    assert "current salary" in said and "notice period" in said


def test_a_page_that_cannot_be_evaluated_is_silent():
    """Диагностика не имеет права ронять отклик."""
    class _Boom:
        def evaluate(self, *a, **k):
            raise RuntimeError("Execution context was destroyed")

    assert _first_field_error(_Boom()) == ""


# --- закрытая вакансия ---------------------------------------------------------
# Живьём 2026-09-05, вакансия 4459508144 (дамп `easyapply-4459508144`). Кнопки
# отклика на странице нет ни одной, все восемь «точек входа» — значки Easy Apply
# на карточках правой колонки, а в `<main>` стоит «Заявки на эту вакансию больше
# не принимаются». Прежний отчёт звал человека подать заявку руками — на
# вакансию, которая заявок не принимает.
#
# Проверка живости на ПОИСКЕ такое поймать не может: она читает страницу
# анонимно по HTTP, а эту строку LinkedIn показывает только вошедшему.

from app.infrastructure.channels.linkedin import _job_page_is_gone


class _Page:
    def __init__(self, main=None, body="", title="Backend Engineer | LinkedIn"):
        self._main, self._body, self._title = main, body, title

    def title(self):
        return self._title

    def locator(self, sel):
        page = self

        class _L:
            @property
            def first(self):
                return self

            def inner_text(self, timeout=None):
                if sel == "main":
                    if page._main is None:
                        raise RuntimeError("нет main")
                    return page._main
                return page._body
        return _L()


def test_the_closed_notice_is_recognised():
    page = _Page(main="droplet.ink\nBackend Engineer\nКалькутта\n"
                      "Заявки на эту вакансию больше не принимаются\nОб этой вакансии")
    assert _job_page_is_gone(page) is True


def test_a_live_job_page_is_not_gone():
    page = _Page(main="droplet.ink\nBackend Engineer\nПростая подача заявки\nОб этой вакансии")
    assert _job_page_is_gone(page) is False


def test_body_is_read_when_there_is_no_main():
    page = _Page(main=None, body="No longer accepting applications")
    assert _job_page_is_gone(page) is True


def test_a_page_that_reads_nothing_is_not_called_gone():
    """Молчание страницы — не доказательство, что вакансия закрыта."""
    class _Boom:
        def title(self):
            raise RuntimeError("нет")

        def locator(self, sel):
            raise RuntimeError("нет")

    assert _job_page_is_gone(_Boom()) is False
