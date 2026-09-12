"""Канал Jobicy: пройти регистрационный гейт и отдать форму работодателя общему коду.

Своей формы у площадки нет — она ведёт на ATS работодателя, и именно поэтому
Jobicy сюда и взяли: последнюю милю уже умеет `external_apply`, тот же код, что
обслуживает LinkedIn, RemoteOK, агрегаторы и прямые ссылки в ATS.

Но дойти до этой ссылки анонимно нельзя, и это измерено, а не предположено
(2026-09-11). Кнопка «Apply Now» на странице вакансии — не ссылка, а `<button>`
с `aria-haspopup="dialog"`, чей onclick шлёт событие с говорящим именем
`RegistrationGateOpened`. Адреса работодателя нет ни в разметке страницы, ни в
пред-отрисованном попапе, ни в `jobDescription` из API: на выборке в 50 вакансий
ссылок в ATS ровно ноль, а внешние ссылки в описаниях ведут на маркетинговые
страницы компаний. Отсюда сохранённая сессия — как у RemoteOK и по той же причине.

Пока сессии нет, `start()` отвечает `ChannelUnavailable`, а не `ChannelError`:
разница в том, что лиды остаются `new` и дождутся входа, вместо того чтобы
сгореть в `failed` пачкой.
"""
from app.domain.channel import (
    ChannelError, ChannelUnavailable, ManualApplyRequired, OutreachContent,
)

# Гейт зовут по-разному в разных раскладках вёрстки, поэтому берём и кнопку, и
# ссылку, и русский вариант. `first` ниже гасит неоднозначность: кнопка «Apply»
# дублируется в шапке и в теле карточки.
_APPLY_SEL = ("button.jv-apply-primary, a.jv-apply-primary, "
              "button:has-text('Apply Now'), a:has-text('Apply Now'), "
              "button:has-text('Apply for this job'), "
              "a:has-text('Apply for this job')")
# Сколько ждать после клика: гейт открывает диалог, а переход на сайт
# работодателя происходит уже из него.
_SETTLE_MS = 3000
_BOARD_HOST = "jobicy.com"


def left_the_board(url: str) -> bool:
    """Ушли ли мы со страницы самой площадки на сайт работодателя."""
    u = (url or "").strip().lower()
    if not u:
        return False
    host = u.split("//")[-1].split("/")[0]
    return not (host == _BOARD_HOST or host.endswith("." + _BOARD_HOST))


class JobicyChannel:
    name = "jobicy"
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
                "Jobicy: нет сохранённой сессии — зарегистрируйся на jobicy.com "
                f"и сделай make login_jobicy ({self._state_path})")
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
            raise ChannelError("JobicyChannel.start() not called")
        job_url = (target or "").strip()
        if not self._ext.get("enabled") or self._ext.get("fn") is None:
            raise ChannelError(
                "Jobicy: отклик идёт через форму работодателя, а автоотклик "
                f"выключен (EXTERNAL_APPLY_ENABLED): {job_url}")

        page = self._page
        page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
        # Описание читается ДО клика: дальше страницы площадки уже не будет, а
        # текст нужен, чтобы отвечать на вопросы работодателя в чужой форме. Тот
        # же порядок, что у RemoteOK и агрегаторов, и по той же причине.
        try:
            desc = page.locator("body").first.inner_text(timeout=5000)[:6000]
        except Exception:  # noqa: BLE001 — контекст для ИИ это бонус, не повод падать
            desc = ""

        try:
            page.locator(_APPLY_SEL).first.click(timeout=10000)
        except Exception as exc:  # noqa: BLE001
            raise ManualApplyRequired(
                f"Jobicy: кнопку отклика не нажать ({exc}) — откликнись "
                f"вручную: {job_url}") from exc
        page.wait_for_timeout(_SETTLE_MS)

        if not left_the_board(page.url):
            # Так заканчивается КАЖДЫЙ лид Jobicy на 2026-09-11, и причина не в
            # нас. Кнопку отклика рисует скрипт в пустой контейнер `_w_<id>`, и
            # он остаётся пустым при живой сессии — проверено на трёх вакансиях
            # двух компаний, и в чистом автоматизированном профиле, и в обычном
            # Chrome владельца. Площадка проверяет свой анти-адблочный флаг
            # `jzwp4eyas8`, тот не выставлен, и виджет не отдаётся.
            #
            # Выбрать «похожую» внешнюю ссылку вместо него нельзя: их на странице
            # десятки — соцсети, магазины приложений, реклама, — и промах означает
            # отклик в чужую вакансию. Тот же принцип, что у канала агрегаторов:
            # лид уходит человеку, а не в угадайку.
            raise ManualApplyRequired(
                "Jobicy: адреса работодателя на странице нет. Замер 2026-09-11 "
                "с живой сессией, три вакансии двух компаний: контейнер отклика "
                "`_w_<id>` остаётся пустым и в чистом профиле, и в обычном Chrome "
                "владельца, а их анти-адблочный флаг `jzwp4eyas8` не выставлен. "
                "Ни API с куками, ни разметка ссылки не отдают. Сессия тут ни при "
                f"чём — откликнись вручную: {job_url}")

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
