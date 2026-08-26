"""Build the 'search finished' Telegram message the worker sends after a run."""


def format_duration(seconds) -> str:
    """Длительность словами, без лишней точности.

    Секунды до минуты, минуты и секунды до часа, дальше часы и минуты: точность
    до десятых тут никому не нужна, а лишние знаки мешают читать строку с
    десятком платформ.
    """
    total = int(max(0, seconds or 0))
    if total < 60:
        return f"{total} с"
    if total < 3600:
        return f"{total // 60} м {total % 60} с"
    return f"{total // 3600} ч {(total % 3600) // 60} м"


def _timing_line(platform: str, seconds, added) -> str:
    """Строка про одну площадку. `added is None` значит, что она упала.

    Различать это обязательно: площадка, упавшая на первой секунде, иначе
    выглядит ровно как площадка, где просто не нашлось вакансий.
    """
    took = format_duration(seconds)
    if added is None:
        return f"• {platform}: {took}, ошибка"
    if added:
        return f"• {platform}: {took}, +{added}"
    return f"• {platform}: {took}, пусто"


def search_done_message(platforms, added: int, timings=None, paused=()) -> str:
    """`timings` — список (платформа, секунды, сколько добавлено или None).

    Поиск идёт по площадкам последовательно и занимает минуты, а из сообщения
    нельзя было понять ни где он застрял, ни какая площадка потратила своё
    время впустую.

    `paused` называет площадки, которых в этом поиске не было из-за паузы. Без
    этой строки они просто отсутствуют в перечислении, а «Поиск завершён» поверх
    неполного списка читается как «искали везде».
    """
    plats = ", ".join(platforms)
    if added:
        # Подтверждать больше нечего: найденное уже лежит лидами `new` и уйдёт
        # ближайшим прогоном. Раньше здесь звали жать /show_vacancies.
        head = (f"✅ Поиск завершён ({plats}): +{added} вакансий — "
                "уже в очереди на отправку.")
    else:
        head = f"✅ Поиск завершён ({plats}): ничего нового."
    if paused:
        head = f"{head}\n⏸  На паузе, не искал: {', '.join(paused)}."
    if not timings:
        return head
    lines = "\n".join(_timing_line(p, s, a) for p, s, a in timings)
    return f"{head}\n\n{lines}"


def search_paused_message(held, remaining) -> str:
    """Что не искали из-за паузы — и, если искать больше нечего, как её снять.

    Один текст на два адреса: в консоль ноута (`make search_linkedin`) и в
    Telegram тому, кто прислал команду из вкладки «Команды», — у строки запроса
    там нет колонки под причину, а красный `error` объясняет не больше, чем
    молчание.

    Отказ обязан быть слышен: человек просил ИМЕННО эту площадку, и тихий выход
    он прочтёт как «поискали, ничего не нашлось».
    """
    plats = ", ".join(held)
    if remaining:
        return (f"⏸  На паузе: {plats} — эти площадки не ищу. "
                f"Ищу остальные: {', '.join(remaining)}.")
    return (f"⏸  На паузе: {plats} — поиск не запускал, искать больше нечего. "
            "Снять паузу: убрать площадку из PAUSED_PLATFORMS в .env.")
