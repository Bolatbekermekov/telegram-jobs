"""Путь от карточки Indeed до формы работодателя. Без браузера.

Замер живой выдачи 2026-09-12 (реальный Chrome, `indeed.com/jobs?q=ai+engineer`):

* обычному HTTP-клиенту площадка отвечает 403 (Cloudflare), живому Chrome —
  200 и 32 карточки. Отсюда весь транспорт через CDP, как у Wellfound;
* вакансия адресуется параметром `jk` (16 hex), а не слагом, как у остальных;
* в выборке из 25 карточек ни одной с внутренним «Easily apply» — все ведут
  «Apply on company site». Это и есть ценность площадки: за редиректом стоит
  ATS работодателя, а его формы `external_apply` уже умеет заполнять;
* адрес работодателя в разметке страницы НЕ лежит: он раскрывается только
  переходом. Поэтому переход и приходится делать браузером, а не разбором HTML.

Стены самого Indeed, которые надо отличать от нормального ухода на ATS:
`/applystart` — Indeed Apply, форма живёт на самом Indeed и ATS-хоста за ней
нет; `secure.indeed.com` — вход; `/challenge` — антибот.
"""
import re

# jk — шестнадцатеричный ключ вакансии. Границу справа задаём явно, иначе
# хвост выдачи («&from=serp») приклеился бы к id.
_JK = re.compile(r"[?&]jk=([0-9a-f]{8,32})\b", re.I)

_BOARD = "indeed.com"

# Форма Indeed Apply: ATS за ней нет, заполнять нечего.
_INDEED_APPLY = re.compile(r"indeed\.com/applystart", re.I)
# Вход. Отдельно от антибота: чинится другой командой.
_LOGIN = re.compile(r"secure\.indeed\.com|indeed\.com/account/login", re.I)
# Антибот. Логином не лечится — лечится живым браузером и паузой.
_CHALLENGE = re.compile(r"indeed\.com/(challenge|blocked)|hcaptcha|cf-chl", re.I)


def job_key(job_url) -> str:
    """Ключ вакансии из её ссылки, или «» если его там нет."""
    m = _JK.search(str(job_url or "").strip())
    return m.group(1) if m else ""


def apply_path(jk: str) -> str:
    """Относительная ссылка отклика — относительная намеренно.

    Переход идёт СО страницы вакансии, уже открытой в браузере: Referer —
    единственное, что отличает нас от прямого захода, а прямой заход Indeed
    отбивает. Та же причина, что у RemoteOK с его `/l/<id>`.
    """
    return f"/rc/clk?jk={jk}"


def left_indeed(url) -> bool:
    """Ушли ли мы с площадки на сайт работодателя.

    Хост сравнивается по меткам, а не подстрокой: `indeed.com.evil.example`
    площадкой не является. Страновых доменов у Indeed десятки (`de.`, `nl.`),
    и все они — всё ещё Indeed.
    """
    u = str(url or "").strip().lower()
    if not u:
        return False
    host = u.split("//")[-1].split("/")[0].split("?")[0].split(":")[0]
    return not (host == _BOARD or host.endswith("." + _BOARD))


def wall_reason(landing_url, job_url: str) -> str | None:
    """Почему отклика по этому адресу нет, или None, если дорога открыта.

    Судит ТОЛЬКО по URL и только про стены самого Indeed. Что лежит за уходом
    на чужой хост — форма, письмо или ничего — по адресу не определить; это
    разбирает `external_apply`, читая саму страницу.
    """
    url = str(landing_url or "")
    if left_indeed(url):
        return None
    if _INDEED_APPLY.search(url):
        return ("Indeed Apply: форма отклика живёт на самом Indeed, ATS "
                "работодателя за ней нет — заполнять нечего, откликнись "
                f"вручную: {job_url}")
    if _CHALLENGE.search(url):
        return ("Indeed показал антибот-проверку вместо перехода — пройди её в "
                f"открытом Chrome и повтори прогон: {job_url}")
    if _LOGIN.search(url):
        return ("Indeed просит войти — сессия в открытом Chrome протухла, "
                f"сделай make login_indeed: {job_url}")
    # Остались на площадке по неизвестной причине. Гадать нельзя: на странице
    # десятки внешних ссылок, и промах означает отклик в чужую вакансию.
    return ("Indeed не увёл на сайт работодателя (остались на "
            f"{url[:80]}) — откликнись вручную: {job_url}")
