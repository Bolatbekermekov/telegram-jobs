"""RemoteOK channel: пройти редирект отклика и отдать форму работодателя дальше.

RemoteOK ничего не принимает у себя — кнопка Apply уводит на сторону. Поэтому
своей логики заполнения здесь нет: обе дороги, куда она приводит, уже закрыты
external_apply (форма ATS) и EmailChannel (почта работодателя). Задача канала —
довести браузер до нужной страницы и не дать ему уткнуться в стену молча.

Отличие от Wellfound: тот обязан работать через CDP, потому что Cloudflare
привязывает своё разрешение к браузеру, который его прошёл. У RemoteOK
Cloudflare нет, и сохранённая сессия работает в СВОЁМ браузере — проверено
живьём 2026-08-03, headless-запуск с remoteok_state.json дошёл до формы Ashby.
Значит воркер может откликаться без открытого окна.

Автоматизация RemoteOK нарушает их ToS и грозит баном аккаунта (принято
пользователем).
"""
from app.domain.channel import (
    ChannelError,
    ChannelUnavailable,
    ManualApplyRequired,
    OutreachContent,
)
from app.domain.remoteok_apply import apply_path, job_id, wall_reason

# Сколько ждать, пока отработает обфусцированный редирект /l/<id>: он
# расшифровывает адрес в JS и только потом переходит, так что события
# навигации к моменту возврата evaluate() ещё нет.
_REDIRECT_SETTLE_MS = 6000


class RemoteOKChannel:
    name = "remoteok"
    body_limit = None
    needs_subject = False

    def __init__(self, state_path: str, headless: bool = True,
                 external_apply_deps=None):
        self._state_path = state_path
        self._headless = headless
        self._ext = external_apply_deps or {"enabled": False, "fn": None}
        self._pw = None
        self._browser = None
        self._page = None

    def start(self) -> None:
        from pathlib import Path

        from patchright.sync_api import sync_playwright

        if not Path(self._state_path).exists():
            raise ChannelUnavailable(
                "RemoteOK: нет сохранённой сессии — сделай make login_remoteok "
                f"({self._state_path})")
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._headless,
                                                 channel="chrome")
        context = self._browser.new_context(storage_state=self._state_path)
        self._page = context.new_page()

    def stop(self) -> None:
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def send(self, target: str, content: OutreachContent) -> None:
        if self._page is None:
            raise ChannelError("RemoteOKChannel.start() not called")
        job_url = (target or "").strip()
        jid = job_id(job_url)
        if not jid:
            raise ChannelError(
                f"RemoteOK: в ссылке нет id вакансии, отклик не открыть: {job_url}")
        if not self._ext.get("enabled") or self._ext.get("fn") is None:
            raise ChannelError(
                "RemoteOK: отклик идёт через внешнюю форму, а автоотклик выключен "
                f"(EXTERNAL_APPLY_ENABLED): {job_url}")

        page = self._page
        page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
        # Описание читается ДО перехода: дальше страницы вакансии уже нет, а
        # текст нужен, чтобы отвечать на вопросы работодателя в форме ATS.
        try:
            desc = page.locator("body").first.inner_text(timeout=5000)[:6000]
        except Exception:  # noqa: BLE001 — контекст для ИИ это бонус, не повод падать
            desc = ""
        # Относительной ссылкой и именно отсюда: /l/<id> без Referer со страницы
        # вакансии отвечает 302 обратно на неё же, и отклик не открывается.
        page.evaluate("() => { window.location.href = '%s'; }" % apply_path(jid))
        page.wait_for_timeout(_REDIRECT_SETTLE_MS)

        blocked = wall_reason(page.url, job_url)
        if blocked:
            raise ManualApplyRequired(blocked)

        fn = self._ext["fn"]
        fn(page, job_url, content,
           profile=self._ext.get("profile"),
           # Резюме той роли, под которую написано письмо. Тот же стык уже
           # чинили в LinkedIn: без этого на любую роль уходит CV из конфига.
           cv_path=content.attachment_path or self._ext.get("cv_path", ""),
           answerer=self._ext.get("answerer"),
           dry_run=self._ext.get("dry_run", False),
           email_channel=self._ext.get("email_channel"),
           subject_maker=self._ext.get("subject_maker"),
           vacancy_context=desc)
