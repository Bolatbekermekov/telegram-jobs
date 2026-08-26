"""Юридический документ вместо страницы отклика.

Кнопка «Apply» не всегда ведёт к форме. Замер 2026-08-26 на Zalando: там стоит
Usercentrics, согласие рисуется в shadow DOM, мы его не видим и не отвечаем — и
кнопка уводит на текст политики обработки данных, где формы нет и дальше пути
тоже нет.

Различать это важно ради ЗАМЕТКИ в таблице. «Форма не распознана: <адрес
политики>» — формально правда, но читается как поломка разбора формы, и человек
идёт искать её не там. Здесь только строки: ни сети, ни браузера.
"""
import re
from urllib.parse import urlsplit

# Сегмент пути, который целиком и есть юридический документ.
_LEGAL_SEGMENT_RE = re.compile(
    r"^(?:[a-z]{2}-)?(?:"
    r"privacy(?:[-_]?(?:policy|statement|notice))?|"
    r"data[-_]?protection(?:[-_]?(?:policy|statement|notice))?|"
    r"[a-z-]*data-protection-statement|"
    r"terms(?:[-_]?(?:of[-_]?(?:use|service)|and[-_]?conditions))?|"
    r"cookie[-_]?(?:policy|notice|settings)?|"
    r"imprint|impressum|datenschutz(?:erklaerung)?|"
    r"legal(?:[-_]notice)?|gdpr|dsgvo"
    r")$", re.IGNORECASE)

# Путь вакансии. Проверяется ПЕРВЫМ: «Privacy Engineer» — это работа, а не
# политика, и вакансия «Data Protection Officer» тоже. Без этой проверки правило
# по подстроке уводило бы такие лиды в ручной отклик ни за что.
_JOB_SEGMENT_RE = re.compile(
    r"^(?:jobs?|careers?|vacanc(?:y|ies)|positions?|opening|apply|"
    r"job_app|application|embed|o|c)$", re.IGNORECASE)


def looks_like_legal_page(url: str | None) -> bool:
    """Это юридический текст, а не страница вакансии или отклика."""
    path = urlsplit(url or "").path
    segments = [s for s in path.split("/") if s]
    if any(_JOB_SEGMENT_RE.match(s) for s in segments):
        return False
    return any(_LEGAL_SEGMENT_RE.match(s) for s in segments)
