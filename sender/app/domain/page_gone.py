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
_GONE_LINE_RE = re.compile(
    r"^(404|not found|closed|position closed|job closed|expired|"
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
