"""Встроенная форма ATS, спрятанная за careers-страницей компании.

Компания ставит на свой сайт скрипт вендора, а форму он подгружает отдельным
запросом. Иногда форма в DOM так и не появляется — тогда для нас страница
выглядит пустой (маршрут NONE), и лид уходит в ручной отклик, хотя настоящая
форма живёт по соседнему адресу у вендора, чей хост уже в белом списке.

Здесь только строки: адрес собирается из того, что страница про себя
рассказывает. Ни сети, ни браузера — чтобы правило можно было проверить.
"""
import re
from urllib.parse import urlsplit

# Имя доски работодателя внутри Greenhouse. Берётся из скрипта, который
# компания вставляет к себе на страницу:
#   <script src="https://boards.greenhouse.io/embed/job_board/js?for=datadog">
# Именно ИМЯ ДОСКИ, а не имя компании: у многих оно вида acme-inc2, и угадать
# его нельзя — по чужому имени попадёшь в чужую вакансию.
_BOARD_RE = re.compile(
    r"greenhouse\.io/embed/job_board/js\?for=([A-Za-z0-9._-]+)", re.IGNORECASE)

# Номер вакансии — три источника, строго в этом порядке надёжности:
#   1) gh_jid в адресе               (careers.datadoghq.com/detail/8052095/?gh_jid=8052095)
#   2) ссылка на форму в разметке    (…/embed/job_app?…token=8052095)
#   3) длинное число в пути адреса   (n26.com/en-eu/careers/positions/7925103)
# Третий — догадка, поэтому он последний и требует шести цифр: в пути careers-
# страницы легко встретить год или номер страницы, и отклик по такому «номеру»
# ушёл бы в чужую вакансию. Номера Greenhouse — семь-восемь цифр.
_JID_URL_RE = re.compile(r"[?&]gh_jid=(\d+)")
_JID_HTML_RE = re.compile(r"job_app\?[^\"'<>]*?token=(\d+)")
_JID_PATH_RE = re.compile(r"/(\d{6,})(?:/|$)")

_GREENHOUSE_HOST_RE = re.compile(r"(^|\.)greenhouse\.io$", re.IGNORECASE)


def greenhouse_embed_url(html: str, page_url: str) -> str:
    """Адрес встроенной формы Greenhouse для этой страницы, или "".

    `boards.greenhouse.io/<доска>/jobs/<id>` для этого не годится: проверено
    2026-08-24 на Datadog — Greenhouse редиректит такой адрес обратно на сайт
    компании, туда же, откуда мы уходим. Форму отдаёт только `/embed/job_app`.
    """
    host = urlsplit(page_url or "").hostname or ""
    if _GREENHOUSE_HOST_RE.search(host):
        return ""      # уже у вендора: иначе переход зациклится

    board = _BOARD_RE.search(html or "")
    if not board:
        return ""

    jid = (_JID_URL_RE.search(page_url or "")
           or _JID_HTML_RE.search(html or "")
           or _JID_PATH_RE.search(urlsplit(page_url or "").path))
    if not jid:
        return ""

    return ("https://job-boards.greenhouse.io/embed/job_app"
            f"?for={board.group(1)}&token={jid.group(1)}")


# Куда вендор кладёт саму форму относительно страницы вакансии. Замерено живьём
# 2026-08-24: у Teamtailor `careers.bluethrone.io/jobs/8175038-…` это страница
# ВАКАНСИИ (полей нет вовсе, а кнопка подписана «Join us» и под селектор
# раскрытия не попадает), форма — на `…/applications/new`, 19 полей. У Recruitee
# `jobs.profitap.com/o/<слаг>` — то же самое, форма на `/o/<слаг>/c/new`.
#
# Только вендоры, чей путь измерен. Догадка тут стоит дорого: чужой адрес — это
# отклик не на ту вакансию, а такое уже случалось.
_VENDOR_APPLY_PATH = {
    "teamtailor.com": "applications/new",
    "recruitee.com": "c/new",
}


def vendor_apply_url(page_url: str, vendor: str | None) -> str:
    """Адрес формы отклика рядом со страницей вакансии, или "".

    `vendor` — имя из белого списка, доказанное делегированием в DNS
    (`apply_guard.vendor_behind`), а не вычитанное из вёрстки: вёрстку пишет сам
    сайт. Поэтому функция вендора не определяет, а только знает, куда у него
    ходить.
    """
    tail = _VENDOR_APPLY_PATH.get((vendor or "").lower())
    if not tail:
        return ""
    base = (page_url or "").split("?", 1)[0].split("#", 1)[0].rstrip("/")
    if not base:
        return ""
    if base.endswith("/" + tail):
        return ""      # уже на форме: иначе ходили бы по кругу
    return f"{base}/{tail}"
