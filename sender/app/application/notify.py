"""Build the 'search finished' Telegram message the worker sends after a run."""


def search_done_message(platforms, added: int) -> str:
    plats = ", ".join(platforms)
    if added:
        return f"✅ Поиск завершён ({plats}): +{added} вакансий.\nЖми /show_vacancies"
    return f"✅ Поиск завершён ({plats}): ничего нового."
