"""Снята ли вакансия — по тому, что страница говорит о себе. Ни сети, ни браузера.

Правило переехало сюда из `infrastructure/channels/external_apply.py` дословно,
и переехало потому, что спрашивающих стало двое. Канал спрашивает, когда уже
открыл страницу браузером и не нашёл на ней формы. Цикл отправки спрашивает
раньше — ДО того, как за письмо заплачено (см. `vacancy_alive.vacancy_gone`).
Разъедься эти двое в том, что считать снятой вакансией, — и в таблице появятся
две разные заметки об одном и том же, а человек будет разбираться, почему.
`external_apply` имя `page_is_gone` по-прежнему экспортирует: тем же приёмом и
по той же причине, по какой `vacancy_fetcher` экспортирует предикаты из
`vacancy_text` — чтобы уже написанные вызовы остались написанными.
"""
import html as _html
import re
from urllib.parse import urlsplit as _urlsplit

# Как эта находка называется в «Заметке». Константа, а не строка в двух местах:
# формулировку читает человек, разбирающий лист, и одна находка должна
# называться одинаково независимо от того, кто её сделал.
GONE_NOTE = "страница недоступна / вакансия неактуальна"

# A dead or closed job link — the page is gone (404) or the posting stopped
# accepting applications. Detected from the title/body so the sheet note reads
# "страница недоступна / вакансия неактуальна" instead of "форма не распознана".
_GONE_RE = re.compile(
    r"no longer (available|accepting|active)"
    r"|(position|role|job|vacancy|posting) (has been |is )?(closed|filled|expired|removed)"
    r"|not accepting applications|page (not found|does ?n'?t exist)|404 error"
    r"|вакансия (снят|закрыт|не найден|неактивн|больше не)|страница не найдена|больше не принима",
    re.I)


# Состояние, объявленное ОТДЕЛЬНОЙ строкой. Сайт не всегда пишет «position
# closed» — чаще рисует статус самостоятельным элементом, и в тексте страницы он
# оказывается строкой сам по себе. Замер 2026-08-24: у Toughbyte это ровно
# «Closed» при обычном заголовке вакансии и HTTP 200, у YouHodler — «404» при
# заголовке «Not Found». Прежний шаблон требовал существительное перед
# состоянием, поэтому оба прошли мимо и легли в таблицу как «форма не
# распознана» — формально верно, а человека отправляет чинить несуществующее.
#
# Требование ЦЕЛОЙ строки здесь несущее: «closed» встречается и в живых
# описаниях («closed-source SDK», «closed beta»), а «404» — в вакансиях про
# обработку ошибок. Отдельной строкой оно стоит только когда это статус.
# «Job not found» и фраза Workday добавлены сюда, а не в поиск по тексту, по той
# же причине, по которой здесь стоит «closed»: в живом описании эти слова живут
# спокойно («handle job not found errors in the scheduler»), состоянием они
# становятся только отдельной строкой. Замер 2026-08-27/28 видимым браузером на
# девяти снятых вакансиях: Ashby рисует «Job not found», Workday — «The page you
# are looking for doesn't exist.». Мимо прежнего правила проходили обе: шаблон
# `page (not found|…)` требует слова «page» вплотную к состоянию, а у Workday
# между ними целое придаточное.
_GONE_LINE_RE = re.compile(
    r"^(404|not found|closed|position closed|job closed|expired|"
    r"job not found|the page you are looking for does ?n['’]?t exist\.?|"
    r"вакансия закрыта|закрыта|снята)$", re.I)


def page_is_gone(title: str, text: str) -> bool:
    """Снята ли вакансия / нет ли страницы — по заголовку и тексту страницы.

    Отделено от Playwright, чтобы правило можно было проверить на снятых живьём
    строках, а не только через браузер.
    """
    if _GONE_RE.search(f"{title} {text}"):
        return True
    if _GONE_LINE_RE.match((title or "").strip()):
        return True
    return any(_GONE_LINE_RE.match(line.strip())
               for line in (text or "").splitlines())


# --- то же правило, но по сырой разметке ------------------------------------
#
# Браузер отдаёт `page.title()` и `body.inner_text()` уже разложенными по
# строкам. У обычного GET есть только разметка, а строки для `_GONE_LINE_RE`
# несущие, поэтому их приходится восстанавливать самим.

_SCRIPT_RE = re.compile(r"(?is)<(script|style|noscript|template)\b.*?</\1>")
_TITLE_RE = re.compile(r"(?is)<title[^>]*>(.*?)</title>")
# Граница строки — граница БЛОЧНОГО элемента, ровно как её видит браузер.
# `button` в списке не для полноты: у Toughbyte состояние написано именно
# `<button disabled>Closed</button>`, а следом в той же обёртке лежит ссылка
# «view all positions» (замер 2026-08-26). Не разорви здесь строку — и правило
# «состояние стоит отдельной строкой» промахнётся мимо той самой страницы,
# ради которой оно писалось.
#
# Строчных тегов (`span`, `a`, `b`) в списке нет, и это не забывчивость: разорви
# строку на них — и «closed» из «We ship <span>closed</span>-source SDKs» станет
# отдельной строкой, то есть состоянием страницы. Живая вакансия при этом молча
# уедет в ручной отклик, а это дороже пропущенной мёртвой.
_BLOCK_RE = re.compile(
    r"(?i)</?(?:p|div|br|hr|h[1-6]|li|ul|ol|dl|dt|dd|tr|td|th|table|thead|tbody|"
    r"section|article|header|footer|nav|aside|main|form|fieldset|legend|label|"
    r"button|option|blockquote|pre|figure|figcaption|details|summary|title)\b[^>]*>")
_TAG_RE = re.compile(r"(?s)<[^>]+>")

# Сколько текста страницы читать. Столько же, сколько читает браузерная проверка
# в канале, — иначе один и тот же сайт получал бы разные вердикты в зависимости
# от того, кто его открыл.
_TEXT_LIMIT = 4000


def page_title(markup: str) -> str:
    m = _TITLE_RE.search(markup or "")
    return " ".join(_html.unescape(m.group(1)).split()) if m else ""


def page_lines(markup: str) -> str:
    """Текст страницы, разложенный по строкам примерно так же, как innerText."""
    text = _SCRIPT_RE.sub(" ", markup or "")
    text = _BLOCK_RE.sub("\n", text)
    text = _TAG_RE.sub(" ", text)
    text = _html.unescape(text)
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)


def html_says_gone(markup: str) -> bool:
    """Говорит ли сырая разметка страницы, что вакансии больше нет."""
    if not markup:
        return False
    return page_is_gone(page_title(markup), page_lines(markup)[:_TEXT_LIMIT])


# --- то же правило, но по АДРЕСУ, на котором мы в итоге оказались -------------
#
# Замер 2026-08-27: 215 ссылок отклика, снятых с 222 случайных карточек remocate
# и прочитанных обычным GET. Мёртвых по правилам выше (404/410 плюс текст
# страницы) — 85. Ещё 53 отвечают ЧЕСТНЫМ 200 и о себе не пишут ничего: сайт
# молча уводит на страницу-заглушку, и единственный след — конечный адрес. Он и
# так уже прочитан (`resp.url` у обычного GET), так что признак не стоит ни
# одного лишнего запроса.
#
# Смертью считаются ровно две формы, обе снятые живьём:
#
#   (А) адрес УКОРОТИЛИ до его же родителя — того, что называло вакансию, в нём
#       больше нет:  `fxpro.bamboohr.com/careers/819` на `/careers`;
#       `wargaming.com/en/careers/vacancy_3329214_nicosia/` на `/en/careers/`;
#       `scorewarrior.recruitee.com/o/…` на `recruitee.com/` (корень чужого хоста);
#   (Б) адресу ПРИПИСАЛИ слово «не найдено»: Greenhouse отвечает `?error=true`,
#       Workable — `?not_found=true`, Rippling — `?rr_message=job_not_found`,
#       Paylocity — `/JobNotFound`, Aviasales — `/<id>/not-found`.
#
# Всё остальное — не смерть, и это в правиле главное. Похороненная живая вакансия
# стоит самой вакансии, пропущенная мёртвая — одной генерации, цены несравнимы.
# Поэтому сравнивается только ПУТЬ и только на укорачивание: `www` и схема,
# добавленный слэш, смена локали (`/en-AR/` на `/en/` у mediacube), новый слаг
# той же вакансии (`/jobs/4894006` на `/jobs/4894006-quantitative-analyst` у
# Teamtailor), переезд на другой хост с тем же путём (`vertex.huntflow.io` на
# `apicworld.huntflow.io`), потерянный utm — всё это проходит мимо.
#
# Проверено на живых: 20 вакансий, стоявших в ленте remocate первыми в день
# замера, — помечено 0. Контроль на одном хосте: `fxpro.bamboohr.com/careers/809`
# (живая) редиректа не даёт вовсе, а `/careers/819` (снятая) уходит на
# `/careers`. Списки BambooHR тринадцати компаний подтвердили каждый вердикт: ни
# одного помеченного id среди живых вакансий нет.

# Слова, которыми АДРЕС сам говорит «такой вакансии нет». Список закрытый и снят
# с живых редиректов: догадка здесь стоит дороже пропуска.
_GONE_URL_RE = re.compile(
    r"(?i)(?:^|[^a-z0-9])(?:404|not[-_]?found|jobnotfound|"
    r"no[-_]?longer[-_]?available|error=true)(?:[^a-z0-9]|$)")

# Хвост, который называет ДЕЙСТВИЕ, а не вакансию. Сняв его, сайт не уводит нас
# с вакансии, а возвращает на неё: `/jobs/123/apply` на `/jobs/123` — это
# по-прежнему та же живая вакансия. Обратный ход у Lever ровно такой же
# (`/<id>/a` на `/<id>/apply`) и тоже живой.
_ACTION_TAIL = frozenset({"apply", "apply-now", "application", "applications",
                          "a", "form", "submit"})


def _address_parts(url: str):
    """(хост без `www`, сегменты пути, строка запроса)."""
    s = _urlsplit((url or "").strip())
    segments = [p for p in s.path.split("/") if p]
    return s.netloc.lower().split(":")[0].removeprefix("www."), segments, s.query


def redirect_says_gone(asked: str, landed: str) -> bool:
    """Увёл ли редирект ПРОЧЬ со страницы вакансии, а не поправил её адрес."""
    if not asked or not landed or asked == landed:
        return False
    asked_host, asked_path, asked_query = _address_parts(asked)
    landed_host, landed_path, landed_query = _address_parts(landed)
    if (asked_host, asked_path, asked_query) == (landed_host, landed_path,
                                                 landed_query):
        return False            # `www`, схема, слэш — адрес тот же самый

    # (Б) слово «не найдено» ПОЯВИЛОСЬ по дороге. «Появилось» здесь несущее:
    # вакансия, у которой такое слово в собственном адресе, редиректом его не
    # заслужила.
    was = "/".join(asked_path) + "?" + asked_query
    now = "/".join(landed_path) + "?" + landed_query
    if _GONE_URL_RE.search(now) and not _GONE_URL_RE.search(was):
        return True

    # (А) путь укоротили до собственного родителя. Только путь: потерянный или
    # добавленный параметр вакансию не отменяет, а витрина с вакансией внутри —
    # обычное дело (`careers.nebius.com/?gh_jid=…` живая).
    if len(landed_path) >= len(asked_path):
        return False
    if asked_path[:len(landed_path)] != landed_path:
        return False
    dropped = asked_path[len(landed_path):]
    return any(part.lower() not in _ACTION_TAIL for part in dropped)


# --- то же правило, но по СКОРЛУПЕ, которую отдаёт SPA-вендор ----------------
#
# Замер 2026-08-27/28. Ashby и Workday отдают дешёвому GET пустой каркас: HTTP
# 200, 6–7 КБ, а «Job not found» дорисовывает JS. Ни код ответа, ни редирект, ни
# текст разметки о смерти не говорят, и лид шёл дальше живым. На 300 карточках
# remocate ссылок на Ashby нашлось 13, мёртвых среди них 4 — все четыре
# проходили мимо.
#
# Дёшево выполнить JS нельзя, а поднимать браузер на каждую проверку живости
# значит отменить то, ради чего проверку заводили дешёвой. Но признак, видимый
# БЕЗ JS, есть, и он ПОЛОЖИТЕЛЬНЫЙ: оба вендора кладут вакансию прямо в `<head>`
# как schema.org JobPosting (`application/ld+json`). Живая страница несёт его
# всегда, снятая — никогда:
#
#     Ashby    206 живых вакансий с 27 досок           — JobPosting у 206
#     Workday  195 живых вакансий у 14 арендаторов     — JobPosting у 195
#     мёртвые  4 Ashby (карточки remocate) + 5 Workday — ни у одной
#
# Все девять мёртвых прочитаны ВИДИМЫМ браузером: Ashby пишет «Job not found»,
# Workday — «The page you are looking for doesn't exist.». Признак не мигает:
# те же 156 живых страниц, прочитанные ещё дважды подряд и вдвое быстрее, чем
# читает прогон, ни разу не пришли скорлупой.
#
# Отсутствие ld+json само по себе смертью НЕ считается — на это правило узкое с
# трёх сторон, и каждая сторона куплена ложным срабатыванием из того же замера:
#
#   (1) Вендор — только измеренный. Живых страниц без ld+json на свете сколько
#       угодно; сказать «нет разметки — значит мертва» можно ровно там, где
#       обратное посчитано. Список вендоров и есть список посчитанного.
#   (2) Адрес обязан называть ОДНУ вакансию. Живая вакансия Workday по адресу
#       `…/job/Data-Engineer_R0240103/apply` отдаёт ту же скорлупу (6449 Б):
#       анкету рисует JS после входа. Так же выглядят корень сайта вакансий
#       (`…/en-US/BAH_Jobs`, 8208 Б) и доска Ashby (`jobs.ashbyhq.com/deel`,
#       10767 Б) — обе живые. Поэтому судится только форма «одна вакансия».
#   (3) Разметка обязана быть маленькой. Девять мёртвых уместились в 5904–7319 Б,
#       самая маленькая живая — 12355 Б у Workday и 19231 Б у Ashby; порог стоит
#       посередине. Условие независимое: перестань вендор класть ld+json — живая
#       страница всё равно останется большой, в ней лежит описание вакансии, и
#       хоронить её мы не начнём.
#
# Цена ошибки прежняя и несимметричная: пропущенная мёртвая стоит одной
# генерации, похороненная живая — самой вакансии. Все три ограничения работают
# в сторону «промолчать».

_SSR_JOB_VENDORS = ("ashbyhq.com", "myworkdayjobs.com")

# Ashby: адрес вакансии — это `/<компания>/<uuid>` и ничего больше. Всё
# остальное на этом хосте (доска компании, подстраница отклика) — не вакансия.
_ASHBY_JOB_ID_RE = re.compile(
    r"(?i)^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
# Workday: вакансию называет сегмент `job` или `details`, а за ним — её имя
# (иногда с городом посередине: `/job/US---Remote/Data-Engineer_R1`).
_WORKDAY_JOB_SEGMENTS = frozenset({"job", "details"})

_SHELL_MAX_BYTES = 10_000
_JSON_LD_RE = re.compile(r"(?is)<script[^>]*ld\+json[^>]*>(.*?)</script>")
_JOB_POSTING_RE = re.compile(r'(?i)"@type"\s*:\s*"JobPosting"')


def _ssr_vendor(host: str) -> str:
    """Вендор из списка, которому принадлежит хост, — по границам меток.

    Подстрокой сравнивать нельзя ровно по той же причине, что и в
    `apply_guard.host_allowed`: `ashbyhq.com.evil.tld` — это evil.tld. Поддомены
    при этом нужны: Workday шардит арендаторов по датацентрам
    (`acme.wd103.myworkdayjobs.com`), и хостов у него столько же, сколько
    клиентов.
    """
    return next((v for v in _SSR_JOB_VENDORS
                 if host == v or host.endswith("." + v)), "")


def _names_one_vacancy(vendor: str, segments: list) -> bool:
    """Называет ли путь ОДНУ вакансию — а не доску, корень или шаг отклика."""
    if any(p.lower() in _ACTION_TAIL for p in segments):
        return False            # `/apply`, `/application` — действие, не вакансия
    if vendor == "ashbyhq.com":
        return len(segments) == 2 and bool(_ASHBY_JOB_ID_RE.match(segments[1]))
    where = next((i for i, p in enumerate(segments)
                  if p.lower() in _WORKDAY_JOB_SEGMENTS), -1)
    # За `job` стоит имя вакансии, иногда с городом перед ним. Больше двух
    # сегментов — это уже шаг мастера отклика (`/apply/useMyLastApplication`).
    return where >= 0 and 1 <= len(segments) - where - 1 <= 2


def spa_shell_says_gone(url: str, markup: str) -> bool:
    """Отдал ли известный SPA-вендор пустую скорлупу вместо страницы вакансии."""
    if not url or not markup or len(markup) >= _SHELL_MAX_BYTES:
        return False
    host, segments, _ = _address_parts(url)
    vendor = _ssr_vendor(host)
    if not vendor or not _names_one_vacancy(vendor, segments):
        return False
    return not any(_JOB_POSTING_RE.search(block)
                   for block in _JSON_LD_RE.findall(markup))
