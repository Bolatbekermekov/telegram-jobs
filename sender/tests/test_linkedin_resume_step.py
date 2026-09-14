"""Шаг «Resume» в Easy Apply: уходит НАШЕ резюме под роль, а не то, что отмечено.

Живьём 2026-09-14 (вакансия 4464869200, снято пробой без отправки): на шаге нет
ни одного `input[type=file]`. Сохранённые резюме нарисованы карточками — внутри
`div[role=radio]` с `aria-label` = имя файла и `aria-checked`, рядом скрытая
радиокнопка; а «Upload resume» — просто кнопка, поле для файла появляется
только по её нажатию. Скрапер видел одну радиогруппу «PDF» с вариантом
«9/14/2026», загружать было некуда, и все заявки через Easy Apply уходили с
уже отмеченным `Bolatbek_Yermekov.pdf` — в настройках аккаунта не нашлось ни
одного резюме под роль (#1200 ушла с файлом 117 362 байта при нашем в 36 434).

Разметка карточки взята с живой страницы, классы и componentkey убраны.
Скрипт повторяет поведение LinkedIn: поле для файла создаётся на клик, новая
карточка после загрузки становится отмеченной.
"""
import pytest

from app.domain.channel import ManualApplyRequired
from app.infrastructure.channels.linkedin import _choose_resume, _resume_card_group_names

JOB = "https://www.linkedin.com/jobs/view/4464869200/"


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


def _card(name: str, checked: bool, n: int) -> str:
    return f"""
    <div><div><p>PDF</p></div>
      <div><p><span>{name}</span></p><p>9/14/2026</p></div>
      <a href="#" target="_blank"><svg role="img" aria-label="Download {name}"></svg></a>
      <div role="radio" tabindex="0" aria-label="{name}" aria-checked="{'true' if checked else 'false'}">
        <input id="r{n}" type="radio" {'checked' if checked else ''} name="radio-group-rr"><label for="r{n}"></label>
      </div>
    </div>"""


_SCRIPT = """
<script>
(() => {
  // Всё внутри функции: set_content меняет документ в том же окне, и
  // объявление верхнего уровня из прошлого теста роняло бы скрипт на `const`.
  // Счётчик и отказ лежат в DOM, а не в window: patchright исполняет evaluate
  // в изолированном мире, и глобальные переменные страницы ему не видны.
  const cards = document.getElementById('cards');
  const body = document.body;
  body.dataset.uploads = '0';
  function select(name) {
    for (const r of cards.querySelectorAll('div[role=radio]')) {
      const on = r.getAttribute('aria-label') === name;
      r.setAttribute('aria-checked', on ? 'true' : 'false');
      r.querySelector('input').checked = on;
    }
  }
  cards.addEventListener('click', e => {
    const r = e.target.closest('div[role=radio]');
    if (r) select(r.getAttribute('aria-label'));
  });
  document.getElementById('upload').addEventListener('click', () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.doc,.docx,.pdf';
    input.addEventListener('change', () => {
      body.dataset.uploads = String(Number(body.dataset.uploads) + 1);
      if (body.dataset.reject === '1') return;
      const name = input.files[0].name;
      const n = cards.querySelectorAll('div[role=radio]').length + 1;
      cards.insertAdjacentHTML('beforeend', `
        <div><div><p>PDF</p></div><div><p><span>${name}</span></p><p>9/14/2026</p></div>
          <div role="radio" tabindex="0" aria-label="${name}" aria-checked="false">
            <input id="r${n}" type="radio" name="radio-group-rr"><label for="r${n}"></label>
          </div></div>`);
      select(name);
    });
    input.click();
  });
})();
</script>
"""


def show(page, cards_html: str, reject: bool = False):
    page.set_content(f"""<body data-reject="{'1' if reject else '0'}"><div role="dialog">
      <h3>Resume*</h3><p>Select or upload a resume in DOC, DOCX, or PDF format that is less than 2MB</p>
      <fieldset id="cards">{cards_html}</fieldset>
      <div><button type="button" id="upload"><span><span>Upload resume</span></span></button></div>
    </div>{_SCRIPT}</body>""")


def _uploads(page) -> int:
    return int(page.evaluate("() => document.body.dataset.uploads"))


def _checked(page) -> list:
    return page.evaluate("""() => [...document.querySelectorAll('div[role=radio][aria-checked=true]')]
        .map(d => d.getAttribute('aria-label'))""")


@pytest.fixture
def role_cv(tmp_path):
    path = tmp_path / "Bolatbek_Yermekov_AI_Engineer.pdf"
    path.write_bytes(b"%PDF-1.4\n% role cv\n")
    return str(path)


def test_the_role_cv_is_uploaded_and_ends_up_selected(page, role_cv):
    show(page, _card("Bolatbek_Yermekov.pdf", True, 1))

    _choose_resume(page, role_cv, JOB)

    assert _checked(page) == ["Bolatbek_Yermekov_AI_Engineer.pdf"]
    assert _uploads(page) == 1


def test_an_already_saved_role_cv_is_picked_without_uploading_again(page, role_cv):
    """Каждая загрузка добавляет резюме в аккаунт — одно и то же не копим."""
    show(page, _card("Bolatbek_Yermekov.pdf", True, 1)
         + _card("Bolatbek_Yermekov_AI_Engineer.pdf", False, 2))

    _choose_resume(page, role_cv, JOB)

    assert _checked(page) == ["Bolatbek_Yermekov_AI_Engineer.pdf"]
    assert _uploads(page) == 0


def test_an_upload_that_never_shows_up_sends_the_lead_to_manual(page, role_cv):
    """Лучше ручной отклик, чем заявка с чужим резюме."""
    show(page, _card("Bolatbek_Yermekov.pdf", True, 1), reject=True)

    with pytest.raises(ManualApplyRequired, match="Bolatbek_Yermekov_AI_Engineer.pdf"):
        _choose_resume(page, role_cv, JOB, wait_ms=1500)


def test_resume_cards_are_not_a_question_for_the_form_filler(page):
    show(page, _card("Bolatbek_Yermekov.pdf", True, 1) + """
      <fieldset><legend>Are you willing to relocate?</legend>
        <label><input type="radio" name="relocate" value="yes">Yes</label>
        <label><input type="radio" name="relocate" value="no">No</label>
      </fieldset>""")

    assert _resume_card_group_names(page) == {"radio-group-rr"}


def test_the_upload_success_toast_is_not_a_refusal(page):
    """Живьём 2026-09-14 (проба без отправки): резюме загрузилось, экран проверки
    показывал Bolatbek_Yermekov_AI_Engineer.pdf, а обход встал с «форма не
    приняла — Resume uploaded successfully»: тост об успехе тоже `role=alert`."""
    from app.infrastructure.channels.linkedin import _first_alert_text

    page.set_content('<body><div role="alert">Resume uploaded successfully</div></body>')
    assert _first_alert_text(page) == ""

    page.set_content('<body><div role="alert">Resume uploaded successfully</div>'
                     '<div role="alert">A resume is required</div></body>')
    assert _first_alert_text(page) == "A resume is required"


# --- обход Easy Apply ---------------------------------------------------------
# Сами решения проверены выше на настоящей разметке; здесь — что обход их зовёт.
# Без этого обе функции могли бы жить и проходить тесты, а заявки уходили бы
# по-старому: с отмеченной чужой карточкой, которую модель «выбирала» как ответ.

def test_the_walk_attaches_the_role_cv_and_keeps_the_cards_away_from_the_planner(monkeypatch):
    from app.application import auto_apply
    from app.application.auto_apply import ApplyPlan
    from app.domain.channel import OutreachContent
    from app.domain.page_observation import FieldObs, PageObservation
    from app.infrastructure.channels import external_apply
    from app.infrastructure.channels import linkedin
    from tests.test_linkedin_channel import _FakeApplyPage

    chosen, planned = [], []
    monkeypatch.setattr(linkedin, "_choose_resume",
                        lambda page, cv_path, job_url, **kw: chosen.append(cv_path))
    monkeypatch.setattr(linkedin, "_resume_card_group_names", lambda page: {"radio-group-rr"})
    step = PageObservation(fields=[
        FieldObs(tag="input", type="radio", name="radio-group-rr", label="PDF",
                 options=["9/14/2026"], ref="0"),
        FieldObs(tag="input", type="text", name="city", label="City", ref="1"),
    ])
    monkeypatch.setattr(external_apply, "scrape_until_ready", lambda page: (step, None))
    monkeypatch.setattr(external_apply, "fill_fields", lambda page, plan, where="": None)
    monkeypatch.setattr(auto_apply, "build_plan",
                        lambda obs, profile, cv_path, cover_letter_path="":
                        planned.extend(f.label for f in obs.fields) or ApplyPlan(actions=[]))
    page = _FakeApplyPage({linkedin.SEL_EASY_APPLY: 1, linkedin.SEL_APPLY_SUBMIT: [0, 1],
                           linkedin.SEL_APPLY_NEXT: 1},
                          href="https://www.linkedin.com/jobs/view/2/apply/")

    linkedin.easy_apply_via_page(page, "https://www.linkedin.com/jobs/view/2",
                                 OutreachContent(body="hi"), profile=object(),
                                 cv_path="/cv/Bolatbek_Yermekov_AI_Engineer.pdf")

    assert chosen == ["/cv/Bolatbek_Yermekov_AI_Engineer.pdf"]
    assert planned == ["City"]
