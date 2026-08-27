"""Pure classifier: a PageObservation -> one outreach Route.

Order matters: a CAPTCHA/login wall wins over everything (can't be automated);
a real fillable apply form wins over an embedded ATS iframe; a known-ATS iframe
wins over a bare mailto. Cookie/consent/search fields are ignored so a cookie
banner is never mistaken for an application form (learned live on superplay.co).
"""
import re

# Сравнение хостов берётся у соседа целиком, а не переписывается здесь: то же
# сравнение стоит перед отправкой (`host_allowed`), и разъедься эти двое — мы
# войдём в iframe, который потом сами же не разрешим заполнять. Список вендоров
# при этом остаётся свой (см. `KNOWN_ATS_HOSTS`): «во что можно войти» и «что
# можно заполнить» — разные вопросы.
from app.application.apply_guard import host_allowed
from app.domain.page_observation import FieldObs, PageObservation, Route

KNOWN_ATS_HOSTS = (
    "comeet.co", "greenhouse.io", "lever.co", "ashbyhq.com", "workable.com",
    "smartrecruiters.com", "teamtailor.com", "recruitee.com", "myworkdayjobs.com",
)

_IGNORE_RE = re.compile(r"cookie|consent|gdpr|newsletter|subscrib|\bsearch\b", re.I)
_APPLY_HINT_RE = re.compile(
    r"name|e-?mail|phone|resume|cv|cover|linkedin|github|portfolio|website|"
    r"salary|experience|first|last|address|city|country|why|message|about|motivat",
    re.I)


def is_real_field(f: FieldObs) -> bool:
    """A field that could belong to a genuine application form."""
    if f.type in ("hidden", "submit", "button", "reset", "image"):
        return False
    if _IGNORE_RE.search(f"{f.label} {f.name}"):
        return False
    return True


def looks_like_apply_form(real_fields: list[FieldObs], file_inputs: int) -> bool:
    """Форма отклика — это загрузка резюме И хотя бы одно поле о человеке.

    Загрузка сама по себе формой не считается, и это не придирка. Скрапер берёт
    `input[type=file]` даже невидимым — иначе резюме не приложится ни на одном
    ATS, они все прячут настоящий вход за своей кнопкой. Значит страница
    ВАКАНСИИ, где форма лежит в скрытом блоке или вовсе на соседнем адресе,
    показывала только эти входы и объявлялась формой.
    Замерено 2026-08-24: `jobs.zalando.com/en/jobs/2723788-…` держит форму в
    `<div id="apply" class="… hidden">`, а Recruitee у `jobs.profitap.com/o/
    qa-engineer-3` — на `/o/<слаг>/c/new`.

    Цена ошибки выше, чем ручной отклик: обязательных незаполненных полей нет
    (полей нет вовсе), CV прикрепляется, `SEL_SUBMIT` находит на странице кнопку
    «Apply», жмёт её, страница уходит на настоящую форму — и проверка отправки
    засчитывает эту навигацию как поданную заявку. Работодатель не получил
    ничего, а лид помечен `sent`. Не объявив форму, мы вместо этого доходим до
    `_reveal_apply_form`, который эту кнопку нажмёт и перечитает уже форму.

    Без загрузки нужны два поля: одинокая коробка «получать вакансии на почту»
    на странице списка (join.com «Apply later») формой не является.
    """
    hits = 0
    for f in real_fields:
        if f.type == "file":
            continue          # загрузка считается отдельно, ниже
        if f.type in ("email", "tel"):
            hits += 1
        elif f.tag in ("input", "textarea") and _APPLY_HINT_RE.search(f"{f.label} {f.name}"):
            hits += 1
    # Счётчик и список полей — два независимых наблюдения одной страницы, и
    # снимок может нести только одно из них. Берём любое: пропустить загрузку
    # значит потребовать два поля там, где хватает одного, и отправить настоящую
    # форму в ручной отклик.
    uploads = file_inputs or sum(1 for f in real_fields if f.type == "file")
    if uploads > 0:
        return hits >= 1
    return hits >= 2


# Домены, зарезервированные RFC 2606 под примеры и тесты. Адрес в такой зоне —
# доказуемо не адрес: `mailto:your-friend@example.com` это кнопка «поделиться
# вакансией с другом», где получателя вписывает человек (Zalando, 2026-08-24).
_PLACEHOLDER_DOMAIN_RE = re.compile(
    r"(^|\.)(example\.(com|net|org)|(example|invalid|test|localhost))$", re.I)

# Ролевые ящики, которые заведомо не про наём. Список узкий намеренно: обычная
# почта компании через отклики и работает — так ушёл лид #380 (info@m-tex.pro),
# — поэтому здесь только то, что доказуемо занято другим. Замер: на странице
# вакансии Zalando после клика «Apply» единственным адресом остаётся
# datenschutz@zalando.de из уведомления о защите данных.
_NOT_HIRING_MAILBOX_RE = re.compile(
    r"^(privacy|datenschutz|dpo|gdpr|legal|compliance|security|abuse|postmaster|"
    r"webmaster|noreply|no-reply|donotreply|do-not-reply|press|media|investor)$",
    re.I)


def has_mailto_address(href: str) -> bool:
    """Годится ли `mailto:` как адрес отклика.

    Три способа промахнуться, все замерены на живых страницах 2026-08-24:

    * адреса нет вовсе — `mailto:?subject=Check out this job`, кнопка
      «поделиться» у Teamtailor (careers.bluethrone.io). Она была на странице
      единственной, маршрут выходил EMAIL, разбор адреса возвращал пустое, и
      отклик умирал с «не разобрал адрес» вместо поиска формы;
    * адрес-пример — `your-friend@example.com` у Zalando, та же кнопка
      «поделиться», но с заполненным для наглядности получателем;
    * адрес не про наём — `datenschutz@zalando.de` из уведомления о защите
      данных, единственный оставшийся на странице после раскрытия формы.

    В двух последних случаях «собачка» на месте, и без этой проверки заявка
    уходила бы в несуществующий ящик или офицеру по приватности. Ручной отклик
    там честнее любой отправки.
    """
    head = (href or "")[len("mailto:"):].split("?", 1)[0].strip().strip("<>")
    if head.count("@") != 1:
        return False
    local, _, domain = head.partition("@")
    if not local or not domain:
        return False
    if _PLACEHOLDER_DOMAIN_RE.search(domain):
        return False
    return not _NOT_HIRING_MAILBOX_RE.match(local)


def known_ats_iframe(iframes: list[str]) -> str | None:
    """Адрес iframe, который РИСУЕТ вендор из списка, — или None.

    Сравнивается ХОСТ. Прежде имя вендора искалось подстрокой во всём адресе, и
    замер 2026-08-27 видимым браузером на живой вакансии SmartRecruiters
    (`jobs.smartrecruiters.com/SmartRecruiters/744000143115219-…`) показал, чем
    это кончается: страницу закрывает капча DataDome, её iframe несёт адрес
    закрытой страницы в ПАРАМЕТРЕ — `geo.captcha-delivery.com/captcha/?…&referer=
    https%3A%2F%2Fjobs.smartrecruiters.com%2F…`, — «smartrecruiters.com» из
    параметра засчитывалось за вендора, маршрут выходил IFRAME_ATS, и
    `_enter_ats_iframe` уводил браузер ВНУТРЬ КАПЧИ вместо формы. Оттуда
    Route.NONE и «форма не распознана» — то есть вместо честного ручного отклика
    прогон тратил браузер на чужой антибот. Тем же путём проходили и пиксели
    аналитики с `utm_source=lever.co`, и `greenhouse.io.evil.tld`.

    Обрезать хост до самого домена при этом нельзя: вендоры шардят по регионам и
    клиентам (`job-boards.greenhouse.io`, `acme.wd3.myworkdayjobs.com`). Ровно
    это и умеет `host_allowed` — совпадение по границам меток плюс поддомены.
    """
    for src in iframes:
        if host_allowed(src, KNOWN_ATS_HOSTS):
            return src
    return None


def classify(obs: PageObservation) -> Route:
    # Only a real login/registration wall is an automatic skip. reCAPTCHA is NOT
    # gated: invisible reCAPTCHA (v3) sits on almost every ATS and does not block
    # filling/submitting, and a visible challenge that truly blocks is caught after
    # submit by the verification step (form did not advance -> manual).
    if obs.login_required:
        return Route.GATED
    real = [f for f in obs.fields if is_real_field(f)]
    if looks_like_apply_form(real, obs.file_inputs):
        return Route.FORM
    if known_ats_iframe(obs.iframes):
        return Route.IFRAME_ATS
    if any(has_mailto_address(h) for h in obs.mailto_links):
        return Route.EMAIL
    return Route.NONE
