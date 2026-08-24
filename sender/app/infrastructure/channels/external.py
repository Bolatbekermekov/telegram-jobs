"""Канал агрегатора вакансий: довести браузер от него до формы работодателя.

Агрегатор не нанимает сам — он ведёт на сайт компании. Своей логики заполнения
здесь нет и быть не должно: то, что лежит за ссылкой, уже разбирает
`external_apply` — тот же код обслуживает внешние отклики LinkedIn и RemoteOK.
Задача канала ровно две: дойти до нужной страницы и не уткнуться в стену молча.

Сессия не нужна — страницы агрегаторов публичные и логина не просят. Этим канал
отличается и от RemoteOK (сохранённое состояние), и от Wellfound (CDP, потому
что Cloudflare привязывает разрешение к прошедшему его браузеру).

Замер живьём 2026-08-22 на remocate.app: среди восьми внешних хостов страницы
семь это шум (CDN Webflow, шрифты Google, соцсети и поддомены самого
агрегатора), осмысленный ровно один — адрес отклика у работодателя. Когда
однозначного кандидата нет, канал отдаёт лид человеку, а не выбирает наугад:
угадывание между похожими ссылками — это ровно то, из-за чего прогон однажды
ушёл откликаться в чужую вакансию.
"""
from app.domain.channel import ChannelError, ManualApplyRequired, OutreachContent
from app.domain.vacancy_text import aggregator_apply_url

# Сколько ждать после перехода на сайт работодателя, прежде чем читать страницу:
# у многих careers-страниц форма рисуется скриптом уже после навигации.
_SETTLE_MS = 2500


class ExternalChannel:
    """Драйвер общий, имя площадки — своё у каждого агрегатора.

    Имя видно в таблице, и «external» там ничего не сообщало: по нему не понять
    ни откуда вакансия, ни есть ли под неё автоматизация. Поэтому имя приходит
    снаружи и называет агрегатор — сегодня это `remocate`, а следующий добавится
    одной строкой в реестре, со своим именем и своим правилом в `contact.py`.
    """

    body_limit = None
    needs_subject = False

    def __init__(self, name: str = "remocate", headless: bool = True,
                 external_apply_deps=None):
        self.name = name
        self._headless = headless
        self._ext = external_apply_deps or {"enabled": False, "fn": None}
        self._pw = None
        self._browser = None
        self._page = None

    def start(self) -> None:
        from patchright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._headless,
                                                 channel="chrome")
        self._page = self._browser.new_context().new_page()

    def stop(self) -> None:
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    def send(self, target: str, content: OutreachContent) -> None:
        if self._page is None:
            raise ChannelError("ExternalChannel.start() not called")
        job_url = (target or "").strip()
        if not self._ext.get("enabled") or self._ext.get("fn") is None:
            raise ChannelError(
                "Внешний отклик выключен (EXTERNAL_APPLY_ENABLED), а у этой "
                f"площадки другого пути нет: {job_url}")

        page = self._page
        page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
        # Описание читается ДО ухода со страницы: дальше её уже нет, а текст
        # нужен, чтобы отвечать на вопросы работодателя в чужой форме. Тот же
        # порядок, что в RemoteOK, и по той же причине.
        try:
            desc = page.locator("body").first.inner_text(timeout=5000)[:6000]
        except Exception:  # noqa: BLE001 — контекст для ИИ это бонус, не повод падать
            desc = ""

        apply_url = aggregator_apply_url(page.content(), job_url)
        if not apply_url:
            raise ManualApplyRequired(
                "не смог однозначно определить ссылку отклика на странице "
                f"вакансии — откликнись вручную: {job_url}")

        page.goto(apply_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(_SETTLE_MS)

        fn = self._ext["fn"]
        # `job_url`, а не `apply_url`: именно эту ссылку показывают человеку,
        # когда отклик просит рук, и именно она лежит в таблице.
        fn(page, job_url, content,
           profile=self._ext.get("profile"),
           # Резюме той роли, под которую написано письмо. Тот же стык уже
           # чинили в LinkedIn и RemoteOK: иначе на любую роль уходит CV из
           # конфига.
           cv_path=content.attachment_path or self._ext.get("cv_path", ""),
           answerer=self._ext.get("answerer"),
           dry_run=self._ext.get("dry_run", False),
           email_channel=self._ext.get("email_channel"),
           subject_maker=self._ext.get("subject_maker"),
           vacancy_context=desc)
