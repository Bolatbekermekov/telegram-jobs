"""Indeed Apply: отклик, который живёт на самом Indeed (`smartapply.indeed.com`).

Решение владельца 2026-09-14: «По Indeed Apply мы должны полностью
автоматизировать. На риски мне без разницы». ToS Indeed от 17.07.2026
автоматизацию отклика запрещает — риск бана аккаунта назван владельцу и принят.
До этого такие лиды уходили в ручные: «форма отклика живёт на самом Indeed»
(#1228, #1230, #1236, #1239).

Замер живьём 2026-09-14 в Chrome из `make login_indeed` (вход выполнен), лиды
#1230, #1236, #1239 — прошли до экрана проверки, ничего не отправив:

* кнопка на странице вакансии — `a[data-testid=viewjob-indeed-apply]` («Apply
  now», www) или `#indeedApplyButton` («Apply with Indeed», ae.indeed.com); обе
  ведут ТУ ЖЕ вкладку на `smartapply.indeed.com/beta/indeedapply/form/…`;
* экраны по порядку: `contact-info-module` (имя, фамилия и телефон уже из
  аккаунта, почта только на чтение) → `profile-location` (индекс, город, улица —
  необязательные) → `resume-selection-module/resume-selection` (карточка
  загруженного файла; новый файл её заменяет) →
  `resume-module/profile-work-experience/create` («Requested by the employer»,
  обязательная должность и «Skip») → вопросы работодателя, если есть →
  `review-module` («Submit your application») → `post-apply`;
* «Continue» — кнопка со случайным data-testid, рядом лежит её невидимая копия:
  жмём видимую по тексту. Поверх кнопок бывает слой, съедающий клик мышью,
  поэтому клики нативные (`el.click()`);
* прямой заход на адрес экрана возвращает к первому — идём только кнопками.

Капчу бот не решает. reCAPTCHA Enterprise там невидимая; если Indeed всё-таки
покажет проверку, отклик уходит человеку.
"""
import re
import time
from pathlib import PurePath
from urllib.parse import urlparse

from app.application.answerer_cv import answerer_for_cv
from app.application.auto_apply import (
    ApplyPlan, already_answered, answer_ai_fields, build_plan,
)
from app.domain.channel import ManualApplyRequired
from app.domain.indeed_apply import on_smartapply
from app.infrastructure.channels.external_apply import (
    _dump_form_debug, _slug, fill_fields, scrape_form,
)

SEL_APPLY_BUTTON = '[data-testid="viewjob-indeed-apply"], #indeedApplyButton'
SEL_RESUME_FILE = ('[data-testid="resume-selection-file-resume-radio-card-file-input"], '
                   'input[type=file]')
SEL_SKIP_EXPERIENCE = ('[data-testid="work-experience-page-create-skip-button"], '
                       '[data-testid="work-experience-page-review-skip-button"]')
SEL_SUBMIT = '[data-testid="submit-application-button"]'

_CONTINUE_RE = r"^\s*(continue|next|review your application|продолжить|далее)\s*$"
_SUCCESS_RE = re.compile(
    r"application has been submitted|application (?:was )?sent|you(?:'|’)ve applied|"
    r"заявка отправлена|отклик отправлен", re.IGNORECASE)
_LOGIN_HOST = "secure.indeed.com"

_MAX_SCREENS = 14
# Экран сохраняется запросом, и адрес меняется только после ответа сервера.
_STEP_WAIT_MS = 20000
# Файл резюме уходит на сервер и разбирается там, прежде чем карточка сменится.
_RESUME_WAIT_MS = 45000
# Сколько ждать, пока экран резюме дорисует карточки и поле загрузки.
_RESUME_SCREEN_WAIT_MS = 15000
_SUBMIT_WAIT_MS = 30000
_POLL_MS = 250
_APPLY_CLICK_ATTEMPTS = 3

_CLICK_BY_TEXT_JS = """(pattern) => {
  const rx = new RegExp(pattern, 'i');
  const shown = e => {
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && getComputedStyle(e).visibility !== 'hidden';
  };
  const button = [...document.querySelectorAll('button, [role=button]')]
    .find(e => !e.disabled && shown(e) && rx.test((e.innerText || e.textContent || '').trim()));
  if (!button) return false;
  button.click();
  return true;
}"""

_SELECTED_RESUME_JS = """() => {
  const card = document.querySelector(
    '[data-testid="resume-selection-file-resume-radio-card"][data-checked="true"]');
  if (!card) return '';
  const label = card.querySelector(
    '[data-testid="resume-selection-file-resume-radio-card-label"]');
  return ((label || card).textContent || '').trim();
}"""

_ERROR_TEXT_JS = """() => {
  const said = [...document.querySelectorAll(
      '[role=alert], [aria-live=assertive], [id$="-errorText"], [data-testid*="error" i]')]
    .filter(e => e.getClientRects().length > 0)
    .map(e => (e.innerText || e.textContent || '').trim()).filter(Boolean);
  return [...new Set(said)].join(' | ').slice(0, 300);
}"""

# Видимая проверка «я не робот»: окно reCAPTCHA с картинками, hCaptcha или
# Cloudflare. Невидимый значок reCAPTCHA Enterprise на каждом экране — не она.
_CHALLENGE_JS = """() => [...document.querySelectorAll('iframe')].some(f =>
  /recaptcha\\/(?:enterprise\\/|api2\\/)?bframe|hcaptcha\\.com|challenges\\.cloudflare\\.com/
    .test(f.src || '') && f.getBoundingClientRect().height > 100)"""


def has_indeed_apply(page) -> bool:
    """Есть ли на странице вакансии кнопка Indeed Apply."""
    try:
        return page.locator(SEL_APPLY_BUTTON).count() > 0
    except Exception:  # noqa: BLE001 — страница ушла из-под нас: кнопки нет
        return False


def indeed_apply_via_page(page, job_url: str, content, profile=None, cv_path: str = "",
                          answerer=None, dry_run: bool = False,
                          vacancy_context: str = "") -> None:
    """Пройти Indeed Apply от страницы вакансии до подтверждения.

    Инвариант тот же, что у Easy Apply и внешних форм: экран, чьи обязательные
    поля не заполняются, останавливает отклик `ManualApplyRequired`, а не
    пропускается. Ссылка для человека — всегда `job_url` из таблицы. При отказе
    экран сохраняется в APPLY_DEBUG_DIR (`indeed_<экран>_<время>`): без этого
    отказы прогона 7 пришлось воспроизводить руками.
    """
    try:
        _walk(page, job_url, content, profile, cv_path, answerer, dry_run, vacancy_context)
    except ManualApplyRequired:
        _dump_form_debug(page, f"indeed_{_slug(_screen(page.url) or 'page')}_{int(time.time())}")
        raise


def _walk(page, job_url, content, profile, cv_path, answerer, dry_run, vacancy_context):
    if not on_smartapply(page.url):
        _open_the_form(page, job_url)
    context = vacancy_context or content.body
    visits: dict[str, int] = {}
    for _ in range(_MAX_SCREENS):
        _check_walls(page, job_url)
        screen = _screen(page.url)
        if screen.startswith("post-apply"):
            return
        visits[screen] = visits.get(screen, 0) + 1
        if visits[screen] > 2:
            raise ManualApplyRequired(
                f"Indeed Apply: экран «{screen}» открылся в третий раз — форма не "
                f"принимает ответы, дожми вручную: {job_url}")
        if screen.startswith("review-module"):
            if dry_run:
                raise ManualApplyRequired(
                    f"DRY_RUN: Indeed Apply дошёл до отправки, НЕ отправлено: {job_url}")
            _submit(page, job_url)
            return
        if "work-experience" in screen:
            _skip_work_experience(page, screen, job_url)
            continue
        if "resume-selection" in screen:
            if cv_path:
                _choose_resume(page, cv_path, job_url)
        elif profile is not None:
            _fill_screen(page, screen, profile, cv_path, answerer, context, job_url)
        _advance(page, screen, job_url)
    raise ManualApplyRequired(
        f"Indeed Apply: не дошёл до отправки за {_MAX_SCREENS} экранов — дожми "
        f"вручную: {job_url}")


def _screen(url: str) -> str:
    path = urlparse(url or "").path
    marker = "/indeedapply/form/"
    return path.split(marker, 1)[1].strip("/") if marker in path else path.strip("/")


def _evaluate(page, script, arg=None, default=None):
    try:
        return page.evaluate(script) if arg is None else page.evaluate(script, arg)
    except Exception:  # noqa: BLE001 — переход посреди чтения: ответа нет
        return default


def _wait_until(page, ready, timeout_ms: int) -> bool:
    waited = 0
    while True:
        try:
            if ready():
                return True
        except Exception:  # noqa: BLE001 — страница как раз перерисовывается
            pass
        if waited >= timeout_ms:
            return False
        page.wait_for_timeout(_POLL_MS)
        waited += _POLL_MS


def _settle(page) -> None:
    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:  # noqa: BLE001 — не дождались: читаем то, что успело прийти
        pass
    _wait_until(page, lambda: page.evaluate("() => !!document.querySelector('h1')"), 10000)


def _click(locator) -> None:
    try:
        locator.evaluate("el => el.click()")
    except Exception:  # noqa: BLE001 — переход, начатый кликом, оборвал ответ evaluate
        pass


def _error_text(page) -> str:
    return _evaluate(page, _ERROR_TEXT_JS, default="") or ""


def _open_the_form(page, job_url: str) -> None:
    button = page.locator(SEL_APPLY_BUTTON)
    if button.count() == 0:
        raise ManualApplyRequired(
            f"Indeed Apply: на странице вакансии нет кнопки отклика — вакансия могла "
            f"закрыться, проверь вручную: {job_url}")
    # Настоящий клик, а не el.click(): «Apply with Indeed» на ae.indeed.com не
    # открыл форму от нативного клика (живьём 2026-09-14, #1236). И не сразу после
    # domcontentloaded: там же настоящий клик до подключения скриптов страницы
    # тоже ничего не открыл (прогон 7). Поэтому ждём загрузку и жмём ещё раз,
    # если форма не пошла. Нативный клик — только если мышь перехвачена слоем.
    try:
        page.wait_for_load_state("load", timeout=15000)
    except Exception:  # noqa: BLE001 — не дождались: жмём по тому, что есть
        pass
    opened = False
    for attempt in range(_APPLY_CLICK_ATTEMPTS):
        try:
            button.first.click(timeout=8000)
        except Exception:  # noqa: BLE001 — клик мышью перехвачен: жмём нативно
            _click(button.first)
        last = attempt == _APPLY_CLICK_ATTEMPTS - 1
        wait = _STEP_WAIT_MS if last else _STEP_WAIT_MS // 3
        if _wait_until(page, lambda: on_smartapply(page.url), wait):
            opened = True
            break
    if not opened:
        _check_walls(page, job_url)
        raise ManualApplyRequired(
            f"Indeed Apply: кнопка нажата, а форма не открылась (остались на "
            f"{page.url[:80]}) — откликнись вручную: {job_url}")


def _check_walls(page, job_url: str) -> None:
    _settle(page)
    if urlparse(page.url or "").hostname == _LOGIN_HOST:
        raise ManualApplyRequired(
            "Indeed Apply: Indeed просит войти — сессия в Chrome протухла, сделай "
            f"make login_indeed и повтори: {job_url}")
    if _evaluate(page, _CHALLENGE_JS, default=False):
        raise ManualApplyRequired(
            "Indeed Apply: Indeed показал проверку «я не робот» — капчу бот не "
            f"проходит, откликнись вручную: {job_url}")


def _selected_resume(page) -> str:
    return _evaluate(page, _SELECTED_RESUME_JS, default="") or ""


def _choose_resume(page, cv_path: str, job_url: str) -> None:
    """Выбранным должно стоять резюме той роли, под которую отклик.

    Живьём 2026-09-14 (#1230) карточкой стоял загруженный 7 августа
    Bolatbek_Yermekov_Fullstack.pdf — на AI-вакансию ушёл бы он.
    """
    name = PurePath(cv_path).name
    # Заголовок «Add a resume» приходит раньше карточек и поля загрузки: Indeed
    # дорисовывает их запросом. Живьём 2026-09-14 (#1228, #1230, #1239) бот
    # смотрел сразу и объявлял, что загрузки файла нет.
    _wait_until(page, lambda: bool(_selected_resume(page))
                or page.locator(SEL_RESUME_FILE).count() > 0, _RESUME_SCREEN_WAIT_MS)
    if _selected_resume(page) == name:
        return
    field = page.locator(SEL_RESUME_FILE)
    if field.count() == 0:
        raise ManualApplyRequired(
            f"Indeed Apply: на шаге резюме нет загрузки файла — {name} не приложить, "
            f"дожми вручную: {job_url}")
    field.first.set_input_files(cv_path)
    if not _wait_until(page, lambda: _selected_resume(page) == name, _RESUME_WAIT_MS):
        raise ManualApplyRequired(
            f"Indeed Apply: резюме {name} не встало (выбрано: "
            f"«{_selected_resume(page) or 'ничего'}») — дожми вручную: {job_url}")


def _skip_work_experience(page, screen: str, job_url: str) -> None:
    """«Requested by the employer», но с «Skip». Должности и даты пошли бы в
    собственное резюме Indeed, а работодатель и так получает наш PDF, где опыт
    расписан; заполнять профиль Indeed за человека незачем."""
    before = page.url
    skip = page.locator(SEL_SKIP_EXPERIENCE)
    if skip.count() == 0:
        raise ManualApplyRequired(
            f"Indeed Apply, экран «{screen}»: нет «Skip», а опыт работы Indeed "
            f"заполнять не из чего — дожми вручную: {job_url}")
    _click(skip.first)
    if not _wait_until(page, lambda: page.url != before, _STEP_WAIT_MS):
        raise ManualApplyRequired(
            f"Indeed Apply, экран «{screen}»: «Skip» не сработал — "
            f"{_error_text(page) or 'экран не сменился'}, дожми вручную: {job_url}")


def _fill_screen(page, screen: str, profile, cv_path: str, answerer, context: str,
                 job_url: str) -> None:
    obs = scrape_form(page)
    plan = build_plan(obs, profile, cv_path)
    # Уже вписанное Indeed из аккаунта не трогаем: телефон там стоит без кода
    # страны рядом с отдельным выбором страны, и строка анкеты «+7 775 720 0604»
    # сломала бы формат (замер 2026-09-14, #1230).
    plan = ApplyPlan(actions=[a for a in plan.actions
                              if a.is_file or not already_answered(a.field)])
    answer_ai_fields(plan, answerer_for_cv(answerer, cv_path), context)
    missing = plan.unmapped_required()
    if missing:
        raise ManualApplyRequired(
            f"Indeed Apply, экран «{screen}»: не заполнены обязательные поля "
            f"{missing} — дожми вручную: {job_url}")
    fill_fields(page, plan, where="Indeed Apply", profile=profile)


def _advance(page, screen: str, job_url: str) -> None:
    before = page.url
    # Кнопку ждём, а не ищем один раз: пока Indeed разбирает загруженный файл или
    # дорисовывает экран, «Continue» выключена или ещё не пришла (живьём
    # 2026-09-14, прогон 7: #1228, #1230, #1239 — «нет кнопки Continue»).
    # None от evaluate — чтение оборвал сам переход, то есть кнопка нажата.
    if not _wait_until(page, lambda: _evaluate(
            page, _CLICK_BY_TEXT_JS, _CONTINUE_RE, default=None) is not False,
            _STEP_WAIT_MS):
        raise ManualApplyRequired(
            f"Indeed Apply, экран «{screen}»: нет кнопки «Continue» — дожми "
            f"вручную: {job_url}")
    if _wait_until(page, lambda: page.url != before, _STEP_WAIT_MS):
        return
    raise ManualApplyRequired(
        f"Indeed Apply, экран «{screen}»: форма не приняла — "
        f"{_error_text(page) or 'экран не сменился'} — дожми вручную: {job_url}")


def _submitted(page) -> bool:
    url = page.url or ""
    if "/post-apply" in url:
        return True
    if "review-module" in url:
        return False
    body = _evaluate(page, "() => document.body ? document.body.innerText : ''", default="")
    return bool(_SUCCESS_RE.search(body or ""))


def _submit(page, job_url: str) -> None:
    button = page.locator(SEL_SUBMIT)
    if button.count() == 0:
        raise ManualApplyRequired(
            f"Indeed Apply: на экране проверки нет «Submit your application» — "
            f"дожми вручную: {job_url}")
    _click(button.first)
    if _wait_until(page, lambda: _submitted(page), _SUBMIT_WAIT_MS):
        return
    if _evaluate(page, _CHALLENGE_JS, default=False):
        reason = "Indeed показал проверку «я не робот»"
    else:
        reason = _error_text(page) or "подтверждения нет"
    raise ManualApplyRequired(
        f"Indeed Apply: «Submit your application» нажата, но {reason}. Проверь "
        f"Indeed → My jobs → Applied, прежде чем откликаться заново: {job_url}")
