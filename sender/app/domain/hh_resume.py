"""Какое онлайн-резюме hh отправлять с откликом — по роли письма.

До 2026-09-14 в аккаунте было одно резюме, «Golang-разработчик», и с ним уходили
все отклики, включая AI-вакансии; PDF под роль попадал только в чат вакансии.
Владелец разрешил завести резюме под роли. На hh они узнаются по названию: id у
каждой копии свой, а название видно человеку и задаётся настройкой
`HH_RESUME_TITLES`.
"""
from pathlib import PurePath

from app.domain.cv_role import ROLES


def parse_role_titles(raw: str) -> dict[str, str]:
    """«ai=AI-инженер (LLM, Python); qa=Тестировщик» -> {роль: название резюме}.

    Неизвестные роли и записи без «=» отбрасываются: молча превратить «devops» в
    fullstack значило бы отправлять не то резюме.
    """
    titles = {}
    for part in (raw or "").split(";"):
        role, sep, title = part.partition("=")
        role, title = role.strip().lower(), title.strip()
        if sep and role in ROLES and title:
            titles[role] = title
    return titles


def hh_resume_title(cv_path, titles: dict[str, str]) -> str:
    """Название резюме для роли приложенного CV, или «» — если выбирать не из чего.

    Роль — это папка CV (`sender/cv/<роль>/…pdf`), та же, из которой CvLibrary
    берёт и текст письма, и вложение.
    """
    if not cv_path:
        return ""
    return titles.get(PurePath(str(cv_path)).parent.name, "")
