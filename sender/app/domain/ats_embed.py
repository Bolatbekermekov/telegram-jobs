"""Встроенная форма ATS, спрятанная за careers-страницей компании.

Компания ставит на свой сайт скрипт вендора, а форму он подгружает отдельным
запросом. Иногда форма в DOM так и не появляется — тогда для нас страница
выглядит пустой (маршрут NONE), и лид уходит в ручной отклик, хотя настоящая
форма живёт по соседнему адресу у вендора, чей хост уже в белом списке.

Здесь только строки: адрес собирается из того, что страница про себя
рассказывает. Ни сети, ни браузера — чтобы правило можно было проверить.
"""
import re
from urllib.parse import parse_qs, urlsplit

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
#
# Workable (замер 2026-09-13, лид #1164): `apply.workable.com/mlabs/j/C3E3C0C056` —
# описание без единого поля, форма — на `…/apply/`, 7 полей.
_VENDOR_APPLY_PATH = {
    "teamtailor.com": "applications/new",
    "recruitee.com": "c/new",
    "workable.com": "apply",
}

# У Workable на одном хосте живут и доски компаний, и вакансии, поэтому хвост
# дописывается только к адресу ОДНОЙ вакансии: к доске `/mlabs/` он дал бы 404.
_ONE_JOB_PATH = {
    "workable.com": re.compile(r"^(?:/[^/]+)?/j/[A-Za-z0-9]+$"),
}

# Teamtailor из LinkedIn иногда ведёт не на вакансию, а в чат-бота:
# `praktika.teamtailor.com/messenger?job_id=8320426`, «Send a message…», полей
# нет. Номер вакансии лежит в `job_id`, а у самой вакансии обычный адрес
# `/jobs/<id>` (замер 2026-09-13, лид #1004: `/jobs/8320426/applications/new` —
# форма из 14 полей).
_TEAMTAILOR_MESSENGER_RE = re.compile(r"^/messenger/?$")


def _vendor_key(vendor: str | None) -> str:
    """Ключ `_VENDOR_APPLY_PATH` для записи белого списка — по границам меток.

    Запись бывает и хостом (`apply.workable.com`, когда страница на хосте самого
    вендора), и доменом (`teamtailor.com`, когда вендора доказал DNS).
    """
    v = (vendor or "").lower().strip(".")
    return next((k for k in _VENDOR_APPLY_PATH
                 if v == k or v.endswith("." + k)), "")


def _job_page(page_url: str, key: str) -> str:
    """Адрес страницы вакансии: чат-бот Teamtailor заменён её собственным адресом."""
    if key != "teamtailor.com":
        return page_url
    parts = urlsplit(page_url)
    if not _TEAMTAILOR_MESSENGER_RE.match(parts.path):
        return page_url
    job_id = parse_qs(parts.query).get("job_id", [""])[0]
    if not job_id.isdigit():
        return ""      # чат без вакансии: форму взять неоткуда
    return f"{parts.scheme}://{parts.netloc}/jobs/{job_id}"


def vendor_apply_url(page_url: str, vendor: str | None) -> str:
    """Адрес формы отклика рядом со страницей вакансии, или "".

    `vendor` — запись белого списка, доказанная хостом самого вендора или
    делегированием в DNS (`apply_guard.vendor_of`), а не вычитанная из вёрстки:
    вёрстку пишет сам сайт. Поэтому функция вендора не определяет, а только
    знает, куда у него ходить.
    """
    key = _vendor_key(vendor)
    if not key:
        return ""
    tail = _VENDOR_APPLY_PATH[key]
    base = _job_page(page_url or "", key).split("?", 1)[0].split("#", 1)[0].rstrip("/")
    if not base:
        return ""
    if base.endswith("/" + tail):
        return ""      # уже на форме: иначе ходили бы по кругу
    one_job = _ONE_JOB_PATH.get(key)
    if one_job and not one_job.match(urlsplit(base).path):
        return ""
    return f"{base}/{tail}"
