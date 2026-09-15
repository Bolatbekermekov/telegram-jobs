"""Поиск по Indeed через живой Chrome пользователя (CDP), как у Wellfound.

Замер 2026-09-12, реальный Chrome на `indeed.com/jobs?q=ai+engineer&l=Remote`:
32 карточки, ни одного челленджа. Тот же запрос обычным HTTP-клиентом — 403
Cloudflare, и так же отвечают страновые домены (`de.`, `nl.`) и мобильная
версия. Своим запущенным браузером площадку тоже не открыть: пропуск Cloudflare
привязан к профилю, который его прошёл. Отсюда CDP к Chrome, поднятому
`make login_indeed`.

Вторая половина замера решает, что попадёт в очередь. Из 25 карточек ни одной
с внутренним «Easily apply» — все ведут на сайт компании, и это для нас плюс:
за редиректом стоит ATS, формы которого `external_apply` уже заполняет. Но
локации сплошь «Remote in Chicago, IL», «Remote in New York, NY» — американская
удалёнка, и в тексте таких вакансий стоит «must be currently authorized to work
in the United States». Кандидату из Казахстана они закрыты, поэтому требование
поднимается отдельной строкой в текст для скорера: иначе он оценит вакансию по
стеку и порекомендует недостижимое.
"""
import re
from dataclasses import dataclass
from urllib.parse import quote_plus

from app.domain.candidate import KIND_JOB, Candidate
from app.domain.indeed_apply import job_key
from app.domain.search_request import per_keyword_limit

INDEED_HOST = "www.indeed.com"
INDEED_BASE_URL = f"https://{INDEED_HOST}"


@dataclass(frozen=True)
class IndeedSite:
    """Где искать: страновой сайт Indeed, его локация и хвост запроса.

    Хвост дописывается к каждому слову. На uk.indeed.com это `"visa
    sponsorship"`, и выдача сама отбирает вакансии, где спонсорство названо, —
    ровно то, что профиль разрешает кандидату без права на работу в этой стране.
    Пустая локация — вся страна.
    """
    host: str
    location: str
    suffix: str


# Хост из настройки открывается в НАСТОЯЩЕМ Chrome человека, под его сессией.
# Поэтому сравнение по меткам, как в `left_indeed`: `indeed.com.evil.example`
# площадкой не является, а `uk.indeed.com` — является.
_HOST_RE = re.compile(r"^(?:[a-z0-9-]+\.)*indeed\.com$")


def parse_indeed_sites(spec: str) -> list[IndeedSite]:
    """Сайты из одной строки настройки: `хост|локация|хвост; хост|…`.

    Разделитель записей — `;`, а не запятая: в локации запятая законна
    («Dubai, UAE»), в хвосте тоже. Пустые части разрешены: `ae.indeed.com` —
    вся страна без хвоста.

    Чужой хост — ошибка, а не пропуск. Молча выброшенная опечатка тихо сделала
    бы прогон меньше задуманного, и узнать об этом было бы не из чего.
    """
    sites: list[IndeedSite] = []
    for entry in (spec or "").split(";"):
        if not entry.strip():
            continue
        host, location, suffix = (entry.split("|") + ["", ""])[:3]
        host = re.sub(r"^https?://", "", host.strip().lower()).rstrip("/")
        if not _HOST_RE.match(host):
            raise ValueError(
                f"INDEED_SITES: «{host}» — не сайт Indeed; ожидается хост вида uk.indeed.com")
        sites.append(IndeedSite(host, location.strip(), suffix.strip()))
    return sites
# Смещение выдачи у Indeed считается в вакансиях, а не в страницах.
_PAGE_STEP = 10
_DESCRIPTION_CAP = 6000
# Контейнер описания, снят с живой страницы 2026-09-12. `#jobDescriptionText` —
# старая разметка Indeed, на нынешних страницах его нет вовсе; актуальный блок
# помечен `data-testid`. Вся страница последним запасным ходом: вёрстка
# меняется, и остаться совсем без текста хуже, чем с шумной шапкой.
_DESCRIPTION_SELECTORS = ('[data-testid="viewjob-job-content"]',
                          "#jobDescriptionText", "body")

# Формулировки сняты с живых вакансий выдачи 2026-09-12. Порядок не важен,
# важна полнота: пропустив требование, мы отдаём скореру вакансию, которая
# выглядит идеальной по стеку и недоступна по факту.
_US_ONLY = re.compile(
    r"authorized to work in the (?:United States|US|U\.S\.)"
    r"|must be (?:located |based )?in the (?:United States|US|U\.S\.)"
    r"|us citizen|green card|security clearance"
    r"|(?:no|unable to (?:provide|offer)|without) (?:visa )?sponsorship"
    r"|do not (?:provide|offer) (?:visa )?sponsorship",
    re.IGNORECASE)


def work_authorization_note(page_text: str) -> str:
    """Строка-предупреждение о праве на работу, или «» если требования нет.

    Отдельной строкой, а не скрытым фильтром: решение «подходит или нет»
    принимает скорер, видя весь текст. Наше дело — чтобы требование не утонуло
    в середине длинного описания.
    """
    m = _US_ONLY.search(str(page_text or ""))
    if not m:
        return ""
    return ("=== ПРАВО НА РАБОТУ ===\n"
            f"В тексте вакансии: «{m.group(0)}». Кандидат из Казахстана, "
            "разрешения на работу в США нет, спонсорство визы не предлагается.")


# Маркеры не-страницы. Снято живьём 2026-09-12: прогон отдал «пусто» за 4 м 32 с,
# и это были четырнадцать таймаутов ожидания карточек подряд — страница в тот
# момент не отрисовалась. Через двадцать минут тот же запрос дал 10 вакансий за
# 2 секунды. Пустая выдача и не открывшаяся страница обязаны различаться: первое
# нормальный рабочий день площадки, второе повод пойти и посмотреть в Chrome.
_CHALLENGE = re.compile(
    r"just a moment|security check|verify you are human|unusual traffic|access denied",
    re.IGNORECASE)

# Страница входа вместо выдачи: сессия Indeed вышла. Живьём 2026-09-15 посреди
# поиска пропали куки SHOE и SOCK, и каждый сайт (US, AE, GB) уводил на
# secure.indeed.com/auth с заголовком «Sign In | Indeed Accounts».
_SIGN_IN_URL = re.compile(r"^https?://secure\.indeed\.com/auth\b", re.IGNORECASE)
_SIGN_IN_TITLE = re.compile(r"\bsign in \| indeed accounts\b", re.IGNORECASE)


def page_state(title: str, body_text: str, card_count: int, url: str = "") -> str:
    """«ready» | «login» | «challenge» | «empty» по тому, что реально на странице.

    Карточки главнее заголовка: если выдача отрисовалась, нам всё равно, что
    Indeed написал в title. «login» — страница входа: её чинит не ожидание, а
    вход в окне Chrome, поэтому это отдельное состояние, а не проверка.
    """
    if card_count > 0:
        return "ready"
    if _SIGN_IN_URL.search(url or "") or _SIGN_IN_TITLE.search(title or ""):
        return "login"
    blob = f"{title or ''} {body_text or ''}"
    return "challenge" if _CHALLENGE.search(blob) else "empty"


def _sign_in_message(instead_of: str, detail: str) -> str:
    """Что сказать, когда вместо выдачи или вакансии Indeed просит войти."""
    return (f"Indeed разлогинил сессию: вместо {instead_of} страница входа. Войди в "
            f"окне Chrome Indeed (make login_indeed) и повтори. {detail}")


def build_jobs_url(keyword: str, location: str, page: int = 1,
                   host: str = INDEED_HOST, suffix: str = "") -> str:
    """Адрес страницы выдачи. Смещение в вакансиях: start=0, 10, 20.

    `host` — страновой сайт (`uk.indeed.com`), `suffix` — хвост запроса
    (`"visa sponsorship"`), см. IndeedSite. Без них адрес ровно прежний.
    """
    start = max(0, (max(1, page) - 1) * _PAGE_STEP)
    query = " ".join(p for p in ((keyword or "").strip(), (suffix or "").strip()) if p)
    parts = [f"q={quote_plus(query)}", f"start={start}"]
    loc = (location or "").strip()
    if loc:
        parts.insert(1, f"l={quote_plus(loc)}")
    return f"https://{host}/jobs?" + "&".join(parts)


def parse_indeed_cards(cards, limit: int) -> list[Candidate]:
    """Карточки выдачи в кандидатов. Чистая функция: Playwright сюда не входит.

    Дедуп обязателен прямо здесь: в разметке одна вакансия представлена двумя
    узлами (замер дал 32 узла на 16 вакансий), и без него половина очереди
    оказалась бы дублями.

    Ключ дедупа — `jk`, а НЕ `normalize_url`. Тот выбрасывает query-строку, а у
    Indeed вакансия адресуется именно ей: `/viewjob?jk=…`. С общим ключом вся
    выдача схлопнулась бы в один адрес `indeed.com/viewjob` — поймано тестом до
    первого прогона.
    """
    found: list[Candidate] = []
    seen: set[str] = set()
    for card in cards:
        href = card.get_href()
        key = job_key(href)
        if not key:
            # Реклама, ссылки на компании и навигация — не вакансии.
            continue
        if key in seen:
            continue
        seen.add(key)
        found.append(Candidate(
            platform="indeed", kind=KIND_JOB, url=href,
            title=card.get_text("title"), company=card.get_text("company"),
            salary=card.get_text("salary"), location=card.get_text("location"),
            summary=""))
        if len(found) >= limit:
            break
    return found


class _LiveCard:
    """Переводит уже прочитанный текст узла в интерфейс парсера."""

    def __init__(self, title, company, location, salary, href):
        self._d = {"title": title, "company": company,
                   "location": location, "salary": salary}
        self._href = href

    def get_text(self, role):
        return (self._d.get(role) or "").strip()

    def get_href(self):
        return self._href


class IndeedChallenge(RuntimeError):
    """Indeed показал проверку вместо страницы.

    Отдельный класс, чтобы обход отличал проверку от любой другой поломки:
    проверка посреди обхода — не повод выбросить уже найденное.
    """


class IndeedSearcher:
    name = "indeed"

    # Карточки снимаются ОДНИМ вызовом в странице, а не локаторами по одной:
    # тридцать узлов на несколько обращений каждый — это сотни round-trip'ов по
    # CDP. Опора — ссылка с параметром `jk` и ближайшие вверх подписи; классы
    # вёрстки в опору не годятся, они меняются с каждой пересборкой.
    _CARDS_JS = """() => {
        const out = [];
        const seen = new Set();
        for (const a of document.querySelectorAll('a[href*="jk="], a[data-jk]')) {
            const href = a.href || '';
            const m = href.match(/[?&]jk=([0-9a-f]{8,32})/i);
            if (!m || seen.has(m[1])) continue;
            seen.add(m[1]);
            let box = a;
            for (let i = 0; i < 8 && box; i++) {
                if (box.querySelector && box.querySelector('[data-testid="company-name"]')) break;
                box = box.parentElement;
            }
            const pick = (sel) => {
                const el = box && box.querySelector ? box.querySelector(sel) : null;
                return el ? (el.innerText || '').trim() : '';
            };
            out.push({
                title: (a.innerText || pick('h2') || '').trim(),
                company: pick('[data-testid="company-name"]'),
                location: pick('[data-testid="text-location"]'),
                salary: pick('[data-testid="attribute_snippet_testid"]'),
                href: href,
            });
        }
        return out;
    }"""

    def __init__(self, cdp_url: str | None = None, per_keyword: int = 25,
                 pages: int = 2, location: str = "Remote", keywords=None,
                 min_delay: float = 8.0, max_delay: float = 20.0, sleep=None,
                 sites=None):
        self._cdp_url = cdp_url
        # Своя выборка слов, а не общая. Причина в устройстве выдачи: Indeed
        # привязан к США, и по общим словам («golang developer», «qa engineer»)
        # он возвращает американскую удалёнку, закрытую кандидату правом на
        # работу. AI-роли — единственная часть выдачи, где хватает
        # международных вакансий, чтобы площадка окупала прогон.
        # Пусто = прежнее поведение, общий список.
        self._keywords = [k for k in (keywords or []) if (k or "").strip()]
        self._per_keyword = per_keyword
        self._pages = pages
        self._location = location
        # Страновые сайты, см. IndeedSite. Пусто — прежний единственный сайт:
        # www.indeed.com с общей локацией, и адреса выдачи побайтно те же.
        self._sites = list(sites or []) or [IndeedSite(INDEED_HOST, location, "")]
        # Пауза между обращениями. Площадка ловит по частоте: замер 2026-09-12
        # показал, что одиночные запросы проходят, а шесть подряд дают «Security
        # Check» с Ray ID в том же Chrome, где ручной просмотр работает.
        # Случайная, а не ровная: ровный интервал сам по себе выглядит машиной.
        self._min_delay = min_delay
        self._max_delay = max_delay
        # Поздним связыванием, а не значением по умолчанию: иначе тест,
        # подменяющий time.sleep, всё равно спал бы по-настоящему.
        self._sleep = sleep
        self._pw = None
        self._browser = None
        self._page = None

    def _pause(self) -> None:
        import random
        import time

        sleep = self._sleep or time.sleep
        sleep(random.uniform(self._min_delay, self._max_delay))

    @property
    def uses_cdp(self) -> bool:
        return self._cdp_url is not None

    def start(self) -> None:
        from patchright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        # Только CDP: запущенный нами браузер получит 403 от Cloudflare, каким
        # бы он ни был. Пропуск привязан к профилю, который его прошёл.
        self._browser = self._pw.chromium.connect_over_cdp(self._cdp_url)
        context = self._browser.contexts[0]
        # Своя вкладка, а не тёплая: поиск и отклик уводят её на чужие сайты, а
        # человек в это время работает в том же окне.
        self._page = context.new_page()

    def stop(self) -> None:
        # Chrome принадлежит человеку — закрываем только свою вкладку и связь.
        try:
            if self._page:
                self._page.close()
        except Exception:  # noqa: BLE001 — вкладку мог закрыть человек
            pass
        if self._pw:
            self._pw.stop()

    def _job_cards(self):
        try:
            # state="attached", а НЕ видимость по умолчанию. Живьём 2026-09-12:
            # первая ссылка на вакансию в разметке Indeed невидима, и ожидание
            # видимости падало по таймауту при полной странице — `querySelectorAll`
            # в тот же момент находил 35 карточек. Боевой поиск из-за этого дважды
            # вернул «пусто». Сборщик читает DOM целиком, видимость ему безразлична.
            self._page.wait_for_selector('a[href*="jk="]', timeout=15000,
                                         state="attached")
        except Exception:  # noqa: BLE001 — либо пусто, либо страница не открылась
            state, detail = self._page_state()
            if state == "login":
                # Одна страница входа говорит за весь обход: сессия общая, и
                # следующие слова и сайты упрутся в тот же вход.
                raise IndeedChallenge(_sign_in_message("выдачи", detail))
            if state == "challenge":
                # Наружу, а не в «пусто»: run_search назовёт это ошибкой, и
                # человек увидит причину вместо молчаливого нуля.
                raise IndeedChallenge(
                    "Indeed показывает проверку вместо выдачи — открой Chrome, "
                    f"пройди её и повтори (make login_indeed поднимает то же окно). {detail}")
            # Пусто — но ПОЧЕМУ пусто, по логу было не понять, и это стоило
            # трёх неверных догадок подряд (холодный старт, ожидание видимости,
            # частота запросов). Теперь страница рассказывает о себе сама.
            print(f"   indeed: карточек не нашлось. {detail}")
            return []
        try:
            raw = self._page.evaluate(self._CARDS_JS)
        except Exception:  # noqa: BLE001
            return []
        return [_LiveCard(title=r.get("title", ""), company=r.get("company", ""),
                          location=r.get("location", ""), salary=r.get("salary", ""),
                          href=r.get("href", "")) for r in raw]

    def _page_state(self):
        """(состояние, человекочитаемая подробность) — для сообщения об ошибке."""
        try:
            cards = self._page.evaluate(
                '() => document.querySelectorAll(\'a[href*="jk="]\').length')
            title = self._page.title()
            url = self._page.url
            body = self._page.locator("body").first.inner_text(timeout=5000)
        except Exception as exc:  # noqa: BLE001 — не смогли спросить, значит не знаем
            return ("empty", f"страницу не опросить: {type(exc).__name__}")
        detail = (f"URL: {str(url)[:90]} | title: {str(title)[:60]} | "
                  f"карточек в DOM: {cards} | текста: {len(body or '')} симв.")
        return (page_state(title, body, cards or 0, url=str(url)), detail)

    def job_cards_for_test(self):
        return self._job_cards()

    def search(self, keywords_list, location, limit) -> list[Candidate]:
        # `location` из общего конфига сюда не годится: «Worldwide» — понятие
        # LinkedIn, а Indeed ждёт либо город, либо «Remote». Локация своя у
        # каждого сайта, см. IndeedSite.
        # Уровень (junior/senior/lead) НЕ фильтруется ни здесь, ни в адресе
        # выдачи: берём любой grade, а годится он или нет решает скорер.
        keywords_list = self._keywords or keywords_list
        per_kw = per_keyword_limit(limit, len(keywords_list), self._per_keyword)
        found: list[Candidate] = []
        seen: set[str] = set()
        # «Пусто» запоминается на пару (сайт, слово): слово, ничего не давшее на
        # одном сайте, на другом может дать полную страницу.
        empty: set = set()
        # Страница снаружи, сайт посередине, слово внутри. Бюджет обрывает
        # перебор, и при обходе «сайт снаружи» первая страна съела бы его целиком.
        for page in range(1, max(1, self._pages) + 1):
            for site in self._sites:
                for kw in keywords_list:
                    if (site, kw) in empty:
                        continue
                    self._pause()
                    try:
                        self._page.goto(
                            build_jobs_url(kw, site.location, page,
                                           host=site.host, suffix=site.suffix),
                            wait_until="domcontentloaded", timeout=45000)
                        cards = self._job_cards()
                    except IndeedChallenge as exc:
                        if not found:
                            raise
                        # Найденное дороже полноты: исключение отсюда `run_search`
                        # ловит на площадку ЦЕЛИКОМ и в таблицу не пишет ничего.
                        print(f"   ⚠️ indeed: проверка на {site.host} посреди обхода — "
                              f"останавливаюсь и отдаю найденное ({len(found)}). {exc}")
                        return found
                    if not cards:
                        empty.add((site, kw))
                        continue
                    for cand in parse_indeed_cards(cards, limit=per_kw):
                        key = job_key(cand.url)      # см. parse_indeed_cards
                        if key in seen:
                            continue
                        seen.add(key)
                        found.append(cand)
                        if len(found) >= limit:
                            return found
        return found

    def describe(self, url: str) -> str:
        """Текст вакансии для скорера, с поднятым наверх правом на работу.

        Берётся БЛОК вакансии, а не вся страница. Замер 2026-09-12: `body`
        отдаёт шапку Indeed («Skip to main content, Home, Company reviews, Sign
        in…»), и у одной из двух проверенных вакансий этой шапкой текст и
        исчерпывался — 980 символов, описания почти ноль. А этот текст идёт и в
        скоринг, и в письмо рекрутёру.

        Вся страница остаётся запасным ходом: вёрстка меняется, и остаться
        совсем без текста хуже, чем с шумной шапкой.

        Кроме одного случая: вместо вакансии стоит проверка. Её текст скорер
        честно оценит низко, а память отказников запомнит вакансию НАВСЕГДА и
        больше её не оценит. Поэтому проверка — исключение: `score_and_filter`
        пропускает такую вакансию, не записывая вердикта.

        Ждётся ЛЮБОЙ из блоков описания, и отсутствующий пропускается сразу.
        Замер живого прогона 2026-09-13: на uk/ae.indeed.com блока
        `viewjob-job-content` нет вовсе, текст лежит в `#jobDescriptionText`, а
        код ждал первый блок 12 с и ещё 8 с пытался прочитать его же — каждая
        вакансия стоила 21 с ожидания пустоты.
        """
        try:
            self._page.goto(url, wait_until="domcontentloaded", timeout=45000)
            self._page.wait_for_selector(", ".join(_DESCRIPTION_SELECTORS[:-1]),
                                         timeout=12000, state="attached")
        except Exception:  # noqa: BLE001 — описание не обязано открыться
            state, detail = self._page_state()
            if state == "login":
                raise IndeedChallenge(_sign_in_message("вакансии", detail))
            if state == "challenge":
                raise IndeedChallenge(
                    f"Indeed показывает проверку вместо вакансии. {detail}")
        text = ""
        for selector in _DESCRIPTION_SELECTORS:
            try:
                loc = self._page.locator(selector)
            except Exception:  # noqa: BLE001 — блока может не быть, идём к запасному
                continue
            try:
                if loc.count() == 0:
                    continue
            except Exception:  # noqa: BLE001 — не смогли спросить: пробуем прочитать
                pass
            try:
                text = loc.first.inner_text(timeout=8000)
            except Exception:  # noqa: BLE001 — блока может не быть, идём к запасному
                continue
            if (text or "").strip():
                break
        text = (text or "").strip()
        if not text:
            return ""
        note = work_authorization_note(text)
        text = text[:_DESCRIPTION_CAP]
        return f"{text}\n\n{note}" if note else text
