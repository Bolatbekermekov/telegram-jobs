"""Убрать мёртвый файл сессии с дороги, не потеряв его.

Файл сессии — единственное свидетельство того, каким был вход, и по нему потом
разбирают, что именно протухло. Поэтому мёртвый не удаляется, а переименовывается:
рядом с проектом уже лежат hh_state.json.dead-2026-08-22 и .dead-2026-09-07,
оба сделаны руками, когда команда входа отказывалась перелогиниваться.
"""
from datetime import date
from pathlib import Path


def retire_dead_state(path: Path, today: date) -> Path | None:
    """Переименовать `path` в `<имя>.dead-YYYY-MM-DD[-N].json`.

    None, если файла нет — это не ошибка, а нормальный первый вход. Суффикс `-N`
    появляется со второго раза за день: перелогиниться дважды за сутки нормально
    (сессию могли снова сбросить), а затирать вчерашнюю улику нечем.
    """
    path = Path(path)
    if not path.exists():
        return None
    stamp = today.isoformat()
    target = path.with_name(f"{path.stem}.dead-{stamp}{path.suffix}")
    n = 2
    while target.exists():
        target = path.with_name(f"{path.stem}.dead-{stamp}-{n}{path.suffix}")
        n += 1
    path.rename(target)
    return target
