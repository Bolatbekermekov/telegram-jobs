"""Собрать PDF сопроводительного письма. Всё, что трогает диск и tectonic.

Best-effort по построению: если tectonic не установлен или сборка не удалась,
возвращается пустая строка, и поле-загрузка остаётся незаполненным — ровно как
было до этой возможности. Отклик из-за собранного не с первого раза PDF падать
не должен.
"""
import subprocess
import tempfile
from pathlib import Path

from app.domain.cover_letter_tex import build_tex

# Сборка идёт на каждый отклик, поэтому ждать её бесконечно нельзя: зависший
# tectonic остановил бы весь прогон.
_TIMEOUT_SECONDS = 90


def render_cover_letter_pdf(body: str, out_dir: str = "",
                            engine: str = "tectonic") -> str:
    """Путь к собранному PDF, или «» если собрать не удалось.

    Файл кладётся во временную папку: он нужен ровно на время отклика, и
    хранить письма к каждому работодателю на диске незачем.
    """
    tex = build_tex(body)
    if not tex:
        return ""
    workdir = Path(out_dir) if out_dir else Path(tempfile.mkdtemp(prefix="cover-"))
    try:
        workdir.mkdir(parents=True, exist_ok=True)
        src = workdir / "cover_letter.tex"
        src.write_text(tex, encoding="utf-8")
        subprocess.run(
            [engine, "--outdir", str(workdir), "--keep-logs", str(src)],
            capture_output=True, timeout=_TIMEOUT_SECONDS, check=True)
    except Exception:  # noqa: BLE001 — нет tectonic, таймаут, ошибка вёрстки
        return ""
    pdf = workdir / "cover_letter.pdf"
    return str(pdf) if pdf.is_file() else ""
