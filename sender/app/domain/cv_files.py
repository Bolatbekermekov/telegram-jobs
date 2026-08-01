"""Где лежит файл CV. Только pathlib: содержимое читает CvLibrary."""
from pathlib import Path

from app.domain.cv_role import DEFAULT_ROLE

CV_SUFFIXES = (".pdf", ".txt")


def _first_cv(directory: Path) -> Path | None:
    """Первый по алфавиту файл-CV прямо в этой папке."""
    if not directory.is_dir():
        return None
    files = sorted(p for p in directory.iterdir()
                   if p.is_file() and p.suffix.lower() in CV_SUFFIXES)
    return files[0] if files else None


def find_role_cv(cv_dir, role: str) -> Path | None:
    """CV для конкретной роли, то есть файл в папке с её именем."""
    return _first_cv(Path(cv_dir) / role)


def find_any_cv(cv_dir, prefer_role: str = DEFAULT_ROLE) -> Path | None:
    """Хоть какое-нибудь CV: верхний уровень, затем prefer_role, затем любая папка.

    Верхний уровень идёт первым ради обратной совместимости: у кого файл лежит
    как раньше, прямо в `sender/cv/`, тот не должен заметить появления папок.
    """
    root = Path(cv_dir)
    if not root.is_dir():
        return None
    found = _first_cv(root) or find_role_cv(root, prefer_role)
    if found is not None:
        return found
    for sub in sorted(p for p in root.iterdir() if p.is_dir()):
        found = _first_cv(sub)
        if found is not None:
            return found
    return None
