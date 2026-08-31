"""Не писать одному человеку дважды. Чистая логика, без похода в лист.

Замер живого листа 2026-08-03: на 113 уникальных получателей нашлось 10
повторов, и не только в Telegram (telegram 4, email 3, linkedin 3). Причина
в том, что на пути отправки не было ПАМЯТИ: `fetch_new_leads` отбирает строки
строго по статусу, `skip_reason` смотрит только платформу и пустой «Источник»,
и ничто не спрашивало, писали ли мы уже по этому адресу.

Правило подобрано по этим же данным, а не по интуиции. Разбор шести пар:

    получатель             разрыв   что это было
    join@preax.ru          9 дней   ОДНА И ТА ЖЕ вакансия
    hr@bellintegrator.ru   9 дней   ОДНА И ТА ЖЕ вакансия
    @amhrann1             10 дней   ОДНА И ТА ЖЕ вакансия
    @perovvaa              2 дня    ОДНА И ТА ЖЕ вакансия
    @hellok1tty0           1 день   ДВЕ РАЗНЫЕ позиции от одного рекрутёра
    @jakson_vill           1 минута у второй строки «Вакансия» пустая

Отсюда видно, почему одного окна по времени мало: три самых явных дубля имели
разрыв 9-10 дней и проскочили бы сквозь любое разумное окно, а единственный
законный повтор случился на следующий день и окном был бы заблокирован.
Поэтому решают два разных признака:

    тот же адрес + та же вакансия  -> не писать НИКОГДА, время не важно
    тот же адрес + другая вакансия -> не писать чаще, чем раз в N дней
"""
import re
from dataclasses import dataclass
from datetime import datetime

from app.domain.candidate import posting_identity
from app.domain.lead import STATUS_SKIPPED

# Мусор, который площадки клеят к ссылке и который меняется от показа к показу.
_QUERY = re.compile(r"[?#].*$")
_SCHEME = re.compile(r"^\w+://")
_TG_HOST = re.compile(r"^(www\.)?(t\.me|telegram\.me)/")

# Слова короче трёх букв — предлоги и союзы, они одинаковы в любых двух текстах
# и только размывают сравнение.
_WORD = re.compile(r"[a-zа-яё0-9+#.]{3,}")

# Порог похожести вакансий, откалиброван на парах выше (containment):
#     одна и та же вакансия   0.341  0.540  0.545  0.548
#     разные вакансии         0.167
# 0.25 стоит посередине с запасом примерно в полтора раза в обе стороны.
# Меньше — начнём резать законные отклики, больше — пропустим слабейший дубль.
SIMILARITY_THRESHOLD = 0.25


@dataclass(frozen=True)
class SentRecord:
    """Одна уже состоявшаяся отправка, как её помнит лист."""

    platform: str
    address: str            # уже нормализованный, см. normalize_address
    vacancy: str
    sent_at: datetime | None
    lead_id: str = ""


def normalize_address(target) -> str:
    """Адрес получателя в форме, по которой два лида можно сравнить.

    Один человек приходит то как `@nick`, то как `t.me/nick`, то ссылкой с
    хвостом трекинга. Без приведения к одному виду половина дублей выглядит
    как разные адреса.
    """
    t = str(target or "").strip().lower()
    if not t:
        return ""
    t = _QUERY.sub("", t)
    t = _SCHEME.sub("", t)
    t = _TG_HOST.sub("", t)
    return t.lstrip("@").rstrip("/")


def vacancy_similarity(a, b) -> float | None:
    """Насколько два описания вакансии — про одну и ту же работу. None, если не с чем сравнивать.

    Мера — доля общих слов от МЕНЬШЕГО набора (containment), а не Jaccard.
    Причина замерена: модель пересказывает вакансию заново при каждом заходе, и
    второй пересказ бывает вдвое длиннее первого. На паре лидов 75/171 Jaccard
    дал 0.142 при фоновом максимуме 0.216 — то есть не отличил дубль от двух
    случайных вакансий. Containment на той же паре даёт 0.341 против 0.167 у
    настоящих разных позиций.
    """
    wa = set(_WORD.findall(str(a or "").lower()))
    wb = set(_WORD.findall(str(b or "").lower()))
    if not wa or not wb:
        return None
    return len(wa & wb) / min(len(wa), len(wb))


# Адреса мало. У hh отклик уходит НА ВАКАНСИЮ, то есть «получатель» — это ссылка,
# а работодатель публикует одно объявление отдельной карточкой в каждом городе:
# ссылки честно разные, и правило «тот же адрес + та же вакансия» их не видит.
#
# Замер листа 2026-08-29, по всей истории отправок: LLC СП Солюшен получил ОДНУ И
# ТУ ЖЕ «AI-разработчик (Python) Junior / Middle» ДВАДЦАТЬ ЧЕТЫРЕ раза за три дня;
# Andersen — 12 откликов, из них по три на «QA Manual Trainee» и «Full Stack Test
# Engineer Trainee»; Т-Банк — четыре раза одну «Frontend-разработчик React».
# Всего правило ниже остановило бы 43 повтора из 94 опознанных объявлений, все на
# hh, и ни одного ложного срабатывания на других площадках.
#
# Дедупликация в поиске (`_unique` -> posting_identity) от этого не спасает: она
# живёт ВНУТРИ одного прогона, а эти копии расползлись по трём дням.
#
# Первая строка «Вакансии» имеет вид «Название — Работодатель»; её пишет поиск.
# Старый формат клал в ту же строку оценку («AI Intern — 92/100: …»), и тогда за
# работодателя принималась проза — поэтому строки с «/100» и слишком длинные
# хвосты в ключ не идут вовсе: пропустить повтор дешевле, чем склеить две разные
# вакансии.
def vacancy_posting(vacancy_text) -> tuple[str, str] | None:
    """(название, работодатель) из первой строки описания, или None."""
    head = (str(vacancy_text or "").strip().splitlines() or [""])[0].strip()
    if "/100" in head or "—" not in head:
        return None
    title, _, company = head.rpartition("—")
    if len(company.strip()) > 60 or len(title.strip()) > 120:
        return None
    return posting_identity(title, company)


def duplicate_reason(lead, history, now: datetime,
                     window_days: int) -> tuple[str, str] | None:
    """Почему этому лиду писать не надо, как (статус, заметка), или None.

    `history` — то, что уже ушло (SentRecord). Порядок не важен.

    Статус `skipped`, а не `failed`: мы сознательно не отправили, ничего не
    сломалось. `failed` в этом проекте значит «попытались и не смогло», и
    смешивать одно с другим — значит потерять смысл обоих.
    """
    address = normalize_address(lead.target)
    if not address:
        # Пустой «Источник» — забота skip_reason. Иначе все безадресные строки
        # схлопнутся в один «адрес» и начнут блокировать друг друга.
        return None

    platform = (lead.platform or "").strip().lower()

    # То же объявление у того же работодателя — не писать НИКОГДА, каким бы ни
    # был адрес. Проверяется до адресного правила: у копий по городам адреса
    # разные, и до сравнения вакансий дело просто не доходило.
    mine = vacancy_posting(lead.vacancy_context or lead.raw_text)
    if mine is not None:
        for past in history:
            if (past.platform or "").strip().lower() != platform:
                continue
            if vacancy_posting(past.vacancy) == mine:
                return (STATUS_SKIPPED,
                        _note("already applied: то же объявление у того же работодателя",
                              past))

    for past in history:
        if past.address != address or (past.platform or "").strip().lower() != platform:
            continue

        similarity = vacancy_similarity(lead.vacancy_context or lead.raw_text,
                                        past.vacancy)
        if similarity is not None and similarity >= SIMILARITY_THRESHOLD:
            return (STATUS_SKIPPED, _note("already applied: та же вакансия", past))

        # Вакансия другая (или сравнить нечем) — остаётся вопрос давности.
        # Неизвестная дата считается «недавно»: без даты в листе остаются
        # `invited` в LinkedIn, где приглашение висит и ответа ещё нет, а это
        # ровно тот случай, когда второе сообщение выглядит навязчивым.
        if past.sent_at is None or (now - past.sent_at).days < window_days:
            return (STATUS_SKIPPED, _note("already applied: писали недавно", past))

    return None


def _note(reason: str, past: SentRecord) -> str:
    """Заметку читает человек, поэтому в ней должно быть, куда смотреть."""
    when = past.sent_at.strftime("%Y-%m-%d") if past.sent_at else "дата не записана"
    who = f"лид #{past.lead_id}" if past.lead_id else "прошлый лид"
    return f"{reason} ({who}, {when})"
