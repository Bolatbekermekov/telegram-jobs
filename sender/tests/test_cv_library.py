"""CvLibrary: роль -> текст CV для промпта и PDF для вложения."""
from app.application.cv_library import CvLibrary, CvVariant


def _touch(path, body=b"%PDF fake"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return path


def _lib(tmp_path, fallback="/нет/такого.pdf"):
    """Загрузчик подменён: настоящий парсит PDF, а нам нужна проверяемая строка."""
    return CvLibrary(tmp_path, fallback, load_text=lambda p: f"ТЕКСТ:{p}")


def test_returns_the_cv_of_the_requested_role(tmp_path):
    want = _touch(tmp_path / "qa" / "Bolatbek_QA.pdf")
    variant = _lib(tmp_path).for_role("qa")
    assert variant == CvVariant(role="qa", text=f"ТЕКСТ:{want}", pdf_path=str(want))


def test_unknown_role_name_falls_back_to_fullstack(tmp_path):
    want = _touch(tmp_path / "fullstack" / "fs.pdf")
    variant = _lib(tmp_path).for_role("devops")
    assert variant.role == "fullstack"
    assert variant.pdf_path == str(want)


def test_missing_role_folder_falls_back_to_fullstack(tmp_path):
    """Роль валидная, но CV под неё ещё не собрали."""
    want = _touch(tmp_path / "fullstack" / "fs.pdf")
    variant = _lib(tmp_path).for_role("mobile")
    assert variant.role == "fullstack"
    assert variant.pdf_path == str(want)


def test_without_any_folder_falls_back_to_the_legacy_file(tmp_path):
    """Последняя ступень: ровно то, что уходит сегодня."""
    legacy = _touch(tmp_path.parent / "legacy.pdf")
    variant = CvLibrary(tmp_path, str(legacy), load_text=lambda p: f"ТЕКСТ:{p}").for_role("ai")
    assert variant.role == "fullstack"
    assert variant.pdf_path == str(legacy)


def test_the_file_is_read_only_once(tmp_path):
    """Разбор PDF дорогой, а лидов в прогоне сотни."""
    _touch(tmp_path / "ai" / "ai.pdf")
    calls = []

    def counting_load(path):
        calls.append(path)
        return "текст"

    lib = CvLibrary(tmp_path, "/нет.pdf", load_text=counting_load)
    lib.for_role("ai")
    lib.for_role("ai")
    assert len(calls) == 1


def test_two_roles_falling_back_to_the_same_file_read_it_once(tmp_path):
    _touch(tmp_path / "fullstack" / "fs.pdf")
    calls = []

    def counting_load(path):
        calls.append(path)
        return "текст"

    lib = CvLibrary(tmp_path, "/нет.pdf", load_text=counting_load)
    lib.for_role("ai")
    lib.for_role("mobile")
    assert len(calls) == 1
