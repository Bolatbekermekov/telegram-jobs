"""Путь от ссылки на вакансию RemoteOK до формы работодателя. Без браузера.

Кнопка Apply на RemoteOK — не ссылка на работодателя, а редирект /l/<id>, и
пройти его непросто (замер живой страницы 2026-08-03):

* тело /l/<id> отдаёт JS, который расшифровывает строку и делает
  window.location.href — то есть без исполнения JS адрес не достать;
* без Referer со страницы вакансии он отвечает 302 обратно на неё же.

Отсюда правило: переход делается ОТНОСИТЕЛЬНОЙ ссылкой со страницы вакансии,
уже открытой в браузере.

Приземляется он в одно из трёх мест, и все три измерены:
  jobs.ashbyhq.com/...           — форма ATS, её заполняет external_apply;
  страница с mailto:hrd@…        — почта работодателя, её шлёт EmailChannel;
  remoteok.com/premium           — экран платной подписки, отклика нет.
"""
import re

# Хвост слага: RemoteOK клеит id вакансии в конец («…-haystack-1135900»).
# Не меньше четырёх цифр — чтобы «go-2» из названия компании не сошло за id.
_TAIL_ID = re.compile(r"(\d{4,})/?$")

_PREMIUM = re.compile(r"remoteok\.com/premium", re.I)
# Регистрация/вход: ровно то, куда RemoteOK уводит гостя с кнопки Apply.
_AUTH = re.compile(r"remoteok\.com/(sign-?up|log-?in|login|register)", re.I)


def job_id(job_url) -> str:
    """Id вакансии из её ссылки, или «» если его там нет."""
    m = _TAIL_ID.search(str(job_url or "").strip())
    return m.group(1) if m else ""


def apply_path(jid: str) -> str:
    """Относительная ссылка отклика — относительная намеренно, см. модуль."""
    return f"/l/{jid}"


def wall_reason(landing_url, job_url: str) -> str | None:
    """Почему по этому адресу отклика нет, или None, если дорога открыта.

    Судит ТОЛЬКО по URL и только про стены самого RemoteOK. Что лежит дальше —
    форма, письмо или ничего — по URL не определить: страница «Redirecting you
    now to your mail app» живёт на remoteok.com и по адресу неотличима от
    страницы вакансии. Это разбирает external_apply, читая саму страницу.
    """
    url = str(landing_url or "")
    if _PREMIUM.search(url):
        return (f"RemoteOK: отклик только по платной подписке Premium "
                f"($14.95/мес) — эту вакансию площадка собрала с чужого сайта: "
                f"{job_url}")
    if _AUTH.search(url):
        return (f"RemoteOK: сессия протухла, площадка просит войти — сделай "
                f"make login_remoteok: {job_url}")
    return None
