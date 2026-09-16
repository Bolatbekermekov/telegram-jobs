"""Вопрос-галочка в анкете работодателя hh не должен быть невидимым для бота.

Живьём 2026-09-16 (лид #1330, ML-инженер в СОГАЗ, прогон 15): отклик не приняли —
«hh: отклик не подтверждён (форма не принята)». Снимок `.hh_chat_debug` показал
почему: две группы ГАЛОЧЕК подсвечены красным как незаполненные («какие документы
в/у у вас есть» и «форма занятости на текущем месте»), при этом радиовопрос про
гражданство бот ответил. Сборщик вопросов читает только `textarea` и
`input[type=radio]`, галочек он не видит вовсе — модель о них и не узнала.

Браузер настоящий, сеть не нужна: разметка подаётся через `set_content`.
"""
import pytest

from app.infrastructure.channels.headhunter import collect_questions


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


# Разметка снята со снимка отказа (вакансия 137144378): вопрос — абзац над
# группой, варианты — подписи контролов с общим именем `task_<id>`.
SOGAZ_QUESTIONS = """
<div data-qa="task-question">
  <p>Укажите, какие документы воинского учёта у вас есть.</p>
  <label><input type="checkbox" name="task_1" value="0"> Есть военный билет</label>
  <label><input type="checkbox" name="task_1" value="1"> Есть приписное свидетельство</label>
  <label><input type="checkbox" name="task_1" value="2"> Невоеннообязанный/-ая</label>
</div>
<div data-qa="task-question">
  <p>Укажите ваше гражданство.</p>
  <label><input type="radio" name="task_2" value="0"> Российское гражданство</label>
  <label><input type="radio" name="task_2" value="1"> Другое</label>
</div>
"""


def test_a_checkbox_question_is_collected_like_a_radio_one(page):
    page.set_content(f"<body>{SOGAZ_QUESTIONS}</body>")

    got = {q["id"]: q for q in collect_questions(page)}

    assert set(got) == {"task_1", "task_2"}
    assert got["task_1"]["type"] == "choice"
    assert "военный билет" in " ".join(got["task_1"]["options"])
    assert "документы воинского учёта" in got["task_1"]["prompt"]


def test_the_radio_question_next_to_it_still_reads_the_same(page):
    page.set_content(f"<body>{SOGAZ_QUESTIONS}</body>")

    got = {q["id"]: q for q in collect_questions(page)}

    assert got["task_2"]["type"] == "choice"
    assert len(got["task_2"]["options"]) == 2
