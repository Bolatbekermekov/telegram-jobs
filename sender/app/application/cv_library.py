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

    Ступень считается непригодной не только когда файла нет, но и когда он
    есть, а текст из него пустой или не читается (скан без текстового слоя,
    битый PDF, не-UTF8 .txt) — иначе письмо ушло бы из CV, зашитого в
    генератор как запасной вариант, а вложением уехал бы PDF совсем другой
    роли.
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
        for candidate, resolved in self._candidates(role):
            text = self._text_for(str(candidate))
            if text:
                return CvVariant(role=resolved, text=text, pdf_path=str(candidate))
        # Ни одна ступень не дала пригодного текста: отдаём последнюю попытку
        # как есть. Письмо напишется из запасного CV в генераторе, но лид
        # уедет, а это главное.
        return CvVariant(role=DEFAULT_ROLE, text="", pdf_path=self._fallback_pdf)

    def _candidates(self, role: str):
        """Ступени отката по порядку, пропуская несуществующие: папка роли,
        папка fullstack, файл, который уходит сегодня."""
        role_path = find_role_cv(self._cv_dir, role)
        if role_path is not None:
            yield role_path, role
        fullstack_path = find_role_cv(self._cv_dir, DEFAULT_ROLE)
        if fullstack_path is not None:
            yield fullstack_path, DEFAULT_ROLE
        fallback_path = Path(self._fallback_pdf)
        if fallback_path.is_file():
            yield fallback_path, DEFAULT_ROLE

    def _text_for(self, path: str) -> str:
        # Кэш по ПУТИ, а не по роли: разбор PDF дорогой, а несколько ролей,
        # откатившихся на один и тот же файл, читать его повторно не должны.
        # Предупреждение печатается ровно здесь, под тем же условием, что и
        # запись в кэш, — то есть один раз на путь, а не на каждый запрос роли.
        if path not in self._text_by_path:
            try:
                text = self._load_text(path)
            except Exception:  # noqa: BLE001 — битый файл это не повод ронять прогон
                text = ""
                print(f"⚠️  CV не читается: {path} — беру следующую ступень отката")
            else:
                if not text:
                    print(f"⚠️  CV пустой: {path} — беру следующую ступень отката")
            self._text_by_path[path] = text
        return self._text_by_path[path]
