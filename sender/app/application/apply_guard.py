"""Guards between untrusted page content and an irreversible submit.

The vacancy text, the employer's screening questions and the field labels of a
third-party ATS all arrive from a page we don't control, and they reach the model
in the same message as the CV. A page can therefore ask the model to do something
other than answer the question — there is no way to make the model reliably tell
an instruction from data.

So these functions don't try to detect an injection. They constrain what an
injection can achieve: only known ATS hosts are auto-filled, and an answer that
carries the candidate's contact details never gets submitted.
"""
import re

# ATS vendors whose forms we understand. Everything else is filled by hand: the
# rules below can't cover a form we've never seen, and a page we don't recognise
# is exactly where an unexpected field layout would show up.
ALLOWED_APPLY_HOSTS = frozenset({
    # Vendors classify_apply already recognises inside an iframe; an IFRAME_ATS
    # route navigates into one of these, so they must be fillable by name.
    "comeet.co",
    "greenhouse.io", "boards.greenhouse.io", "job-boards.greenhouse.io",
    "lever.co", "jobs.lever.co",
    "ashbyhq.com", "jobs.ashbyhq.com",
    "workable.com", "apply.workable.com",
    "smartrecruiters.com", "jobs.smartrecruiters.com",
    "myworkdayjobs.com",
    "bamboohr.com",
    "teamtailor.com",
    "recruitee.com",
    "personio.de", "jobs.personio.de",
    "join.com",
    "breezy.hr",
    "jazzhr.com", "applytojob.com",
    "hh.ru",
    "wellfound.com",
    "linkedin.com",
})


def _registrable(host: str) -> str:
    """Last two labels of a host — `boards.greenhouse.io` -> `greenhouse.io`.

    Deliberately naive: it is only used as a *second* chance to match the
    allowlist, so a multi-part public suffix (`co.uk`) can at worst fail to
    match and send the lead to a manual apply.
    """
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def _host_of(url: str) -> str:
    from urllib.parse import urlsplit

    return (urlsplit(url).hostname or "").lower().strip(".")


def _allowed_entry(host: str, allowed=ALLOWED_APPLY_HOSTS) -> str | None:
    """The allowlist entry `host` matches, or None.

    Matches the host itself, its registrable domain, and any subdomain of an
    allowed entry (`eu.myworkdayjobs.com`), so vendors that shard by region or
    customer work without listing every host. Matching is on label boundaries,
    never on substrings: `greenhouse.io.evil.tld` is not greenhouse.io.
    """
    host = (host or "").lower().strip(".")
    if not host:
        return None
    if host in allowed:
        return host
    if _registrable(host) in allowed:
        return _registrable(host)
    return next((a for a in allowed if host.endswith("." + a)), None)


def host_allowed(url: str, allowed=ALLOWED_APPLY_HOSTS) -> bool:
    """True when `url`'s host is an ATS we auto-fill."""
    return _allowed_entry(_host_of(url), allowed) is not None


# --- вендор за собственным доменом компании ---------------------------------
#
# Замерено живьём 2026-08-24: два отклика ушли в ручной режим с «незнакомый
# сайт», хотя движок под ними был из списка выше:
#   jobs.profitap.com/o/qa-engineer-3          -> Recruitee
#   careers.bluethrone.io/jobs/8175038-...     -> Teamtailor
# Второй показателен: путь /jobs/<7-значный id>-<слаг> читался как Greenhouse, а
# это Teamtailor. Опознавать вендора по форме URL — гадание, и оно ошиблось.
#
# По вёрстке вендор виден сразу (у profitap 15 ссылок на careers.recruiteecdn.com
# и «atsHost»:«recruitee.com», у bluethrone 21 скрипт с assets-aws.teamtailor-cdn
# .com), но разметку целиком пишет тот, от кого мы защищаемся: строку
# `<script src="https://assets-aws.teamtailor-cdn.com/...">` любой сайт положит
# к себе за секунду. Признак из страницы не доказывает ничего о странице.
# Сертификат тоже пусто: у всех замеренных хостов это обычный Let's Encrypt с
# единственным SAN на сам домен компании, имени вендора там нет.
#
# Доказывает делегирование в DNS: jobs.profitap.com CNAME secure.recruitee.com.
# Кто ставит такой CNAME, тот отдаёт хост вендору целиком — запрос уезжает на
# сервер Recruitee, и своей вёрстки владелец домена там уже не покажет. Границу
# доверия это не двигает: страница, отрисованная Recruitee по адресу
# jobs.profitap.com, ровно то же самое, что company.recruitee.com, который
# разрешён с самого начала — вёрстка формы вендорская, текст вакансии клиентский.
#
# Чего проверка НЕ ловит, и это осознанно: рассинхрон DNS (нам отдали CNAME, а
# браузеру — свой A-запис) и вендоров, которые заводят клиентские домены не на
# своём имени. У Greenhouse это in.saascustomdomains.com, у Ashby своих доменов
# нет вовсе (docs.ashbyhq.com, проверено 2026-08-24) — такие остаются ручными.
# Любая неудача (нет ответа, таймаут, чужой вендор) означает ручной отклик.
_DOH_URL = "https://dns.google/resolve"
_DOH_TIMEOUT_S = 4.0
# socket.gethostbyname_ex не годится: 2026-08-24 для careers.bluethrone.io он
# цепочку вернул, а для jobs.profitap.com отдал только сам хост — системный
# резолвер CNAME схлопывает. Пропущенная цепочка читалась бы как «не вендор».

# Один прогон берёт с площадки несколько вакансий подряд, и хост у них общий.
# Кладём только непустые цепочки: закешировать разовый сбой сети значит держать
# площадку в ручном режиме до конца процесса.
_CHAIN_CACHE: dict[str, tuple[str, ...]] = {}


def cname_targets(payload) -> tuple[str, ...]:
    """Цели CNAME из ответа dns.google, в порядке разрешения.

    Формат живого ответа (снят 2026-08-24): {"Status": 0, "Answer": [{"name":
    "jobs.profitap.com.", "type": 5, "data": "secure.recruitee.com."}, ...]},
    где type 5 — CNAME, а type 1 — уже адрес. Всё, что не разобралось, — пустая
    цепочка: «не доказали» лучше, чем догадка о формате.
    """
    if not isinstance(payload, dict) or payload.get("Status") != 0:
        return ()
    answer = payload.get("Answer")
    if not isinstance(answer, list):
        return ()
    targets = []
    for rec in answer:
        if not isinstance(rec, dict) or rec.get("type") != 5:
            continue
        target = str(rec.get("data") or "").lower().strip(".")
        if target:
            targets.append(target)
    return tuple(targets)


def _cname_chain(host: str) -> tuple[str, ...]:
    if host in _CHAIN_CACHE:
        return _CHAIN_CACHE[host]
    import httpx

    try:
        resp = httpx.get(_DOH_URL, params={"name": host, "type": "A"},
                         timeout=_DOH_TIMEOUT_S)
        resp.raise_for_status()
        chain = cname_targets(resp.json())
    except Exception:  # noqa: BLE001 — вендор не доказан, значит ручной отклик
        return ()
    if chain:
        _CHAIN_CACHE[host] = chain
    return chain


def vendor_behind(url: str, allowed=ALLOWED_APPLY_HOSTS, resolve=None) -> str | None:
    """Вендор из `allowed`, которому делегирован хост `url`, или None.

    Цепочку CNAME проверяем целиком: у Teamtailor клиентский домен идёт через
    ext.teamtailor.com и дальше в section.io, а части клиентов вендор выдаёт
    личный хост (careers.voi.com -> 2zx972fqcl81m.ext.teamtailor.com). Хопы
    после вендорского выбирает уже зона вендора, так что попасть в неё чужой
    записью нельзя. Сравнение — тем же `_allowed_entry`, по границам меток:
    в живой цепочке есть ext.teamtailor.com.c.section.io, и это section.io.
    """
    host = _host_of(url)
    if not host:
        return None
    try:
        chain = (resolve or _cname_chain)(host)
    except Exception:  # noqa: BLE001 — резолвер упал: вендора не доказали
        return None
    for target in chain or ():
        vendor = _allowed_entry(target, allowed)
        if vendor:
            return vendor
    return None


def host_or_vendor_allowed(url: str, allowed=ALLOWED_APPLY_HOSTS,
                           resolve=None) -> bool:
    """`host_allowed`, а если хост не в списке — тот же список по цепочке CNAME.

    Порядок важен: у разрешённого хоста DNS не спрашиваем вовсе, иначе упавший
    резолвер уводил бы в ручной отклик и boards.greenhouse.io.
    """
    return host_allowed(url, allowed) or vendor_behind(url, allowed, resolve) is not None


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def leaked_secrets(text: str, profile) -> list[str]:
    """Names of the profile's contact details that `text` reproduces.

    A model answering "tell us about yourself" has no reason to restate the
    candidate's email or phone number — the ATS collects those in their own
    fields. When one shows up in free text, the likeliest cause is a page that
    asked for it, so the answer must not be submitted.
    """
    found = []
    low = (text or "").lower()

    email = (getattr(profile, "email", "") or "").strip().lower()
    if email and email in low:
        found.append("email")

    # Compare digits only: "+7 (700) 123-45-67" and "77001234567" are one number.
    phone = _digits(getattr(profile, "phone", ""))
    if len(phone) >= 7 and phone[-7:] in _digits(text):
        found.append("phone")

    for attr in ("linkedin", "github", "portfolio"):
        val = (getattr(profile, attr, "") or "").strip().lower()
        if len(val) >= 8 and val in low:
            found.append(attr)

    return found
