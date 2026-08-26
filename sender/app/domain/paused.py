"""Площадка на паузе: прогон её не трогает, но и лиды её не хоронит.

Появилось после бана LinkedIn 2026-08-26. До этого выключателя не было вовсе:
проверка приглашённых открывает LinkedIn в начале КАЖДОГО прогона, поэтому
забаненный аккаунт светился даже тогда, когда отправить нужно было только
Remocate.

Пауза намеренно не имеет статуса в таблице. Лид приостановленной площадки
остаётся `new` — его просто не берут в этот прогон. `skipped` здесь был бы
ошибкой: он означает «с этим лидом покончено», прогон его больше не поднимет,
и человек, которому мы собирались написать, исчез бы из очереди молча. Пауза
временная по смыслу, а `skipped` — нет.
"""


def parse_paused(raw: str | None) -> frozenset[str]:
    """Имена площадок из переменной окружения: "linkedin, hh" -> {linkedin, hh}.

    Регистр и пробелы съедаются: строку правят руками в .env. Пустые куски
    отбрасываются — иначе "linkedin,," дал бы площадку "", и на неё совпал бы
    любой лид без площадки.
    """
    return frozenset(
        part.strip().lower() for part in (raw or "").split(",") if part.strip())


def is_paused(platform: str | None, paused) -> bool:
    """Стоит ли эта площадка на паузе прямо сейчас."""
    name = (platform or "").strip().lower()
    return bool(name) and name in paused


def partition_paused(leads, paused):
    """Очередь прогона и то, что ждёт снятия паузы: (runnable, held).

    Порядок сохраняется — прогон идёт строго по id сверху вниз, и ChannelSwitcher
    рассчитывает именно на это (переключение канала стоит дорого).
    """
    runnable, held = [], []
    for lead in leads:
        (held if is_paused(getattr(lead, "platform", ""), paused) else runnable).append(lead)
    return runnable, held
