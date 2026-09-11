"""Канал прямой ссылки в ATS работодателя: Greenhouse, Lever, Ashby и прочие.

Отличие от канала агрегаторов ровно одно, и оно определяет весь класс. Агрегатор
не нанимает сам, поэтому `ExternalChannel` ищет у него на странице единственную
осмысленную внешнюю ссылку и прыгает по ней на сайт работодателя. Здесь прыгать
некуда: это уже сайт работодателя. Форма либо на странице, либо дорисовывается
скриптом, либо лежит в iframe вендора, либо прячется за кнопкой «Apply» — и всё
это `external_apply` разбирает сам (`scrape_until_ready`, `_reveal_apply_form`,
`_hop_to_embedded_form`, `_enter_ats_iframe`).

Прогонять такую ссылку через поиск «единственной внешней ссылки» было бы хуже,
чем бесполезно: на странице Greenhouse внешних хостов хватает — политика, соцсети,
сайт компании, — и канал либо отдал бы лид в ручные, либо ушёл откликаться не туда.

Сессии у канала нет: страницы ATS публичные и логина не просят. Этим он похож на
канал агрегаторов и отличается от RemoteOK (сохранённое состояние) и Wellfound
(CDP ради Cloudflare).

Замер 2026-09-11 по живым вакансиям: Greenhouse, Lever, SmartRecruiters и
Personio отдают текст вакансии прямо в HTML, Workday, Teamtailor и Recruitee — в
JSON-LD, а Ashby и Workable не отдают его без выполнения JS вообще. Для последних
двух описание, прочитанное здесь браузером, — единственный источник контекста для
ответов на вопросы работодателя.
"""
from app.domain.channel import ChannelError, OutreachContent

# Сколько ждать после навигации, прежде чем читать страницу: у части ATS форма
# рисуется скриптом уже после загрузки. `external_apply` дальше доопрашивает её
# сам (`scrape_until_ready`), так что это только первая, дешёвая попытка.
_SETTLE_MS = 2500


class AtsChannel:
    """Драйвер общий на всех вендоров: различает их не он, а разметка страницы.

    Имя площадки одно — `ats`. Маршрутизация в `classify_apply` идёт по тому, что
    на странице, а не по хосту, список хостов уже живёт в `apply_guard`, а какой
    именно вендор попался, видно в «Источнике». Одиннадцать имён вместо одного
    дали бы одиннадцать веток реестра и ни одного нового ответа.
    """

    name = "ats"
    body_limit = None
    needs_subject = False

    def __init__(self, headless: bool = True, external_apply_deps=None):
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
            raise ChannelError("AtsChannel.start() not called")
        job_url = (target or "").strip()
        if not self._ext.get("enabled") or self._ext.get("fn") is None:
            raise ChannelError(
                "Внешний отклик выключен (EXTERNAL_APPLY_ENABLED), а у этой "
                f"площадки другого пути нет: {job_url}")

        page = self._page
        page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(_SETTLE_MS)
        # Описание читается ДО того, как форму начнут трогать: заполнение уводит
        # со страницы (iframe вендора, встроенная форма Greenhouse), а текст нужен,
        # чтобы отвечать на вопросы работодателя. Тот же порядок, что у агрегаторов
        # и RemoteOK, и по той же причине.
        try:
            desc = page.locator("body").first.inner_text(timeout=5000)[:6000]
        except Exception:  # noqa: BLE001 — контекст для ИИ это бонус, не повод падать
            desc = ""

        self._ext["fn"](
            page, job_url, content,
            profile=self._ext.get("profile"),
            # Резюме той роли, под которую написано письмо, а не из конфига.
            cv_path=content.attachment_path or self._ext.get("cv_path", ""),
            answerer=self._ext.get("answerer"),
            dry_run=self._ext.get("dry_run", False),
            email_channel=self._ext.get("email_channel"),
            subject_maker=self._ext.get("subject_maker"),
            vacancy_context=desc)
