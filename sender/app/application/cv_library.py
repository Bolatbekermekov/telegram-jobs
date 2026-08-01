"""Роль -> CV: текст для промпта и файл для вложения, с откатами."""
from dataclasses import dataclass
from pathlib import Path

from app.domain.cv_files import find_role_cv
from app.domain.cv_role import DEFAULT_ROLE, normalize_role
from app.infrastructure.cv_loader import load_cv_text


@dataclass(frozen=True)
class CvVariant:
    role: str        # роль, чьё CV РЕАЛЬНО отдали (после откатов), а не запрошенная
    text: str        # для промпта генерации письма
    pdf_path: str    # для вложения к письму


class CvLibrary:
    """Отдаёт CV под роль, откатываясь до тех пор, пока что-нибудь не найдётся.

    Цепочка: папка роли -> папка fullstack -> файл, который уходит сегодня.
    Последняя ступень важнее всего: она гарантирует, что худший случай равен
    нынешнему поведению, и ни один лид не остаётся без CV.
    """

    def __init__(self, cv_dir, fallback_pdf: str, load_text=load_cv_text):
        self._cv_dir = Path(cv_dir)
        self._fallback_pdf = fallback_pdf
        self._load_text = load_text
        self._by_role: dict[str, CvVariant] = {}
        self._text_by_path: dict[str, str] = {}

    def for_role(self, role: str) -> CvVariant:
        role = normalize_role(role)
        if role not in self._by_role:
            self._by_role[role] = self._build(role)
        return self._by_role[role]

    def _build(self, role: str) -> CvVariant:
        path = find_role_cv(self._cv_dir, role)
        resolved = role
        if path is None:
            path = find_role_cv(self._cv_dir, DEFAULT_ROLE)
            resolved = DEFAULT_ROLE
        if path is None:
            path = Path(self._fallback_pdf)
            resolved = DEFAULT_ROLE
        return CvVariant(role=resolved, text=self._text_for(str(path)),
                         pdf_path=str(path))

    def _text_for(self, path: str) -> str:
        # Кэш по ПУТИ, а не по роли: разбор PDF дорогой, а несколько ролей,
        # откатившихся на один и тот же файл, читать его повторно не должны.
        if path not in self._text_by_path:
            self._text_by_path[path] = self._load_text(path)
        return self._text_by_path[path]
