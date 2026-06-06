"""Loads CV text from a PDF (or .txt) for use in message generation."""
from pathlib import Path

from pypdf import PdfReader


def load_cv_text(cv_path: str) -> str:
    path = Path(cv_path)
    if not path.exists():
        raise FileNotFoundError(f"CV not found at {cv_path}")
    if path.suffix.lower() == ".pdf":
        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    return path.read_text(encoding="utf-8").strip()


def load_text_file(path: str) -> str:
    return Path(path).read_text(encoding="utf-8").strip()
