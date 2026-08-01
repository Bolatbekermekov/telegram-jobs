"""Поиск файла CV. Чистый pathlib, никакой загрузки содержимого."""
from app.domain.cv_files import find_any_cv, find_role_cv


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4 fake")
    return path


def test_finds_the_pdf_in_the_role_folder(tmp_path):
    want = _touch(tmp_path / "qa" / "Bolatbek_QA.pdf")
    assert find_role_cv(tmp_path, "qa") == want


def test_missing_role_folder_gives_none(tmp_path):
    assert find_role_cv(tmp_path, "qa") is None


def test_empty_role_folder_gives_none(tmp_path):
    (tmp_path / "qa").mkdir()
    assert find_role_cv(tmp_path, "qa") is None


def test_ignores_files_that_are_not_a_cv(tmp_path):
    (tmp_path / "qa").mkdir()
    (tmp_path / "qa" / "cv.tex").write_text("\\documentclass{article}")
    (tmp_path / "qa" / ".DS_Store").write_bytes(b"junk")
    assert find_role_cv(tmp_path, "qa") is None


def test_txt_counts_as_a_cv(tmp_path):
    want = _touch(tmp_path / "ai" / "cv.txt")
    assert find_role_cv(tmp_path, "ai") == want


def test_any_cv_prefers_a_top_level_file(tmp_path):
    """Обратная совместимость: у кого CV лежит как раньше, тот ничего не заметит."""
    top = _touch(tmp_path / "Bolatbek.pdf")
    _touch(tmp_path / "ai" / "ai.pdf")
    assert find_any_cv(tmp_path) == top


def test_any_cv_then_prefers_the_default_role(tmp_path):
    """Без файла наверху берём fullstack, а не первую папку по алфавиту."""
    _touch(tmp_path / "ai" / "ai.pdf")
    want = _touch(tmp_path / "fullstack" / "fs.pdf")
    assert find_any_cv(tmp_path) == want


def test_any_cv_falls_back_to_the_first_subfolder(tmp_path):
    want = _touch(tmp_path / "ai" / "ai.pdf")
    _touch(tmp_path / "mobile" / "mob.pdf")
    assert find_any_cv(tmp_path) == want


def test_any_cv_on_an_empty_dir_gives_none(tmp_path):
    assert find_any_cv(tmp_path) is None


def test_any_cv_on_a_missing_dir_gives_none(tmp_path):
    assert find_any_cv(tmp_path / "нет-такой") is None
