"""Канал Indeed: пройти редирект площадки и отдать форму работодателя общему коду.

Гибрид двух существующих каналов, и оба заимствования вынужденные.

Транспорт — от Wellfound: подключение по CDP к Chrome, который человек поднял
`make login_indeed`. Своим браузером Indeed не открыть: замер 2026-09-12 дал
403 Cloudflare обычному клиенту и 200 с 32 карточками живому Chrome, причём
пропуск привязан к профилю, который его прошёл.

Тело отправки — от RemoteOK: открыть вакансию, прочитать описание ДО перехода,
пройти редирект относительной ссылкой, посмотреть, куда приземлились, и только
потом отдать страницу в `external_apply`. Адрес работодателя в разметке не
лежит — он раскрывается переходом, поэтому переход обязателен.

Отличие от обоих: работаем в СВОЕЙ вкладке. Wellfound берёт тёплую вкладку
человека, но там отклик заполняется на самой площадке; здесь он уводит на чужие
сайты, и делать это во вкладке, где человек работает, нельзя.
"""
from app.domain.channel import (
    ChannelError, ChannelUnavailable, ManualApplyRequired, OutreachContent,
)
from app.domain.indeed_apply import apply_path, job_key, wall_reason

# Редирект расшифровывается в JS, и к возврату из evaluate() события навигации
# ещё нет. Та же пауза и по той же причине, что у RemoteOK.
_REDIRECT_SETTLE_MS = 6000
_DESCRIPTION_CAP = 6000


class IndeedChannel:
    name = "indeed"
    body_limit = None
    needs_subject = False

    def __init__(self, cdp_url: str, external_apply_deps=None, dry_run: bool = False):
        self._cdp_url = cdp_url
        self._ext = external_apply_deps or {"enabled": False, "fn": None}
        self._dry_run = dry_run
        self._pw = None
        self._browser = None
        self._page = None

    def start(self) -> None:
        from patchright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.connect_over_cdp(self._cdp_url)
        except Exception as exc:  # noqa: BLE001 — Chrome не поднят или порт закрыт
            self._pw.stop()
            self._pw = None
            # ChannelUnavailable, а не ChannelError: лиды остаются `new` и
            # дождутся Chrome, вместо того чтобы сгореть в `failed` пачкой.
            raise ChannelUnavailable(
                "Indeed: Chrome не запущен — сделай make login_indeed и оставь "
                f"окно открытым ({exc})")
        context = (self._browser.contexts[0] if self._browser.contexts
                   else self._browser.new_context())
        self._page = context.new_page()

    def stop(self) -> None:
        # Chrome принадлежит человеку: закрываем только свою вкладку и связь.
        try:
            if self._page:
                self._page.close()
        except Exception:  # noqa: BLE001 — вкладку мог закрыть человек
            pass
        if self._pw:
            self._pw.stop()

    def send(self, target: str, content: OutreachContent) -> None:
        if self._page is None:
            raise ChannelError("IndeedChannel.start() not called")
        job_url = (target or "").strip()
        jk = job_key(job_url)
        if not jk:
            raise ChannelError(
                f"Indeed: в ссылке нет ключа вакансии, отклик не открыть: {job_url}")
        if not self._ext.get("enabled") or self._ext.get("fn") is None:
            raise ChannelError(
                "Indeed: своей формы у площадки нет, отклик идёт на сайте "
                f"работодателя, а автоотклик выключен (EXTERNAL_APPLY_ENABLED): {job_url}")

        page = self._page
        page.goto(job_url, wait_until="domcontentloaded", timeout=45000)
        # Описание читается ДО перехода: дальше страницы вакансии уже нет, а
        # текст нужен, чтобы отвечать на вопросы работодателя в форме ATS.
        try:
            desc = page.locator("body").first.inner_text(timeout=8000)[:_DESCRIPTION_CAP]
        except Exception:  # noqa: BLE001 — контекст для ИИ это бонус, не повод падать
            desc = ""

        # Переход ОТНОСИТЕЛЬНОЙ ссылкой изнутри страницы, а не page.goto:
        # Referer со страницы вакансии — единственное, что отличает нас от
        # прямого захода, который Indeed отбивает.
        page.evaluate("() => { window.location.href = '%s'; }" % apply_path(jk))
        page.wait_for_timeout(_REDIRECT_SETTLE_MS)

        blocked = wall_reason(page.url, job_url)
        if blocked:
            raise ManualApplyRequired(blocked)

        self._ext["fn"](
            page, job_url, content,
            profile=self._ext.get("profile"),
            # Резюме той роли, под которую написано письмо, а не из конфига.
            cv_path=content.attachment_path or self._ext.get("cv_path", ""),
            answerer=self._ext.get("answerer"),
            dry_run=self._ext.get("dry_run", self._dry_run),
            email_channel=self._ext.get("email_channel"),
            subject_maker=self._ext.get("subject_maker"),
            vacancy_context=desc)
