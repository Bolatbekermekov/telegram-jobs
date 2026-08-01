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


def test_a_role_whose_file_reads_as_empty_falls_back_to_fullstack(tmp_path):
    """Скан без текстового слоя, пустой .txt — text="" не должен уехать как
    есть: письмо писалось бы из CV, зашитого в генератор как запасной
    вариант, а вложением уехал бы PDF роли, чей текст в письмо не попал."""
    empty_pdf = _touch(tmp_path / "qa" / "Bolatbek_QA.pdf")
    fs_pdf = _touch(tmp_path / "fullstack" / "fs.pdf")

    def load_text(path):
        return "" if path == str(empty_pdf) else f"ТЕКСТ:{path}"

    variant = CvLibrary(tmp_path, "/нет.pdf", load_text=load_text).for_role("qa")

    assert variant.role == "fullstack"
    assert variant.pdf_path == str(fs_pdf)
    assert variant.text == f"ТЕКСТ:{fs_pdf}"


def test_a_role_whose_file_cannot_be_read_falls_back_to_fullstack(tmp_path):
    """Битый PDF/не-UTF8 .txt не должен ронять прогон: ошибка чтения
    проглатывается так же, как пустой текст, и лид всё равно уезжает — с
    fullstack CV, а не с половиной пары (пустое письмо + чужой PDF)."""
    broken_pdf = _touch(tmp_path / "qa" / "Bolatbek_QA.pdf")
    fs_pdf = _touch(tmp_path / "fullstack" / "fs.pdf")

    def load_text(path):
        if path == str(broken_pdf):
            raise ValueError("битый PDF")
        return f"ТЕКСТ:{path}"

    variant = CvLibrary(tmp_path, "/нет.pdf", load_text=load_text).for_role("qa")

    assert variant.role == "fullstack"
    assert variant.pdf_path == str(fs_pdf)
    assert variant.text == f"ТЕКСТ:{fs_pdf}"


def test_an_unreadable_cv_prints_a_warning_naming_the_path(tmp_path, capsys):
    """Молчаливый откат на fullstack не даёт оператору отличить 'модель так
    решила' от 'резюме под роль сломано' — предупреждение обязано назвать
    путь, который не прочитался."""
    broken_pdf = _touch(tmp_path / "qa" / "Bolatbek_QA.pdf")
    _touch(tmp_path / "fullstack" / "fs.pdf")

    def load_text(path):
        if path == str(broken_pdf):
            raise ValueError("битый PDF")
        return f"ТЕКСТ:{path}"

    CvLibrary(tmp_path, "/нет.pdf", load_text=load_text).for_role("qa")

    out = capsys.readouterr().out
    assert "CV не читается" in out
    assert str(broken_pdf) in out


def test_an_empty_cv_prints_a_warning_naming_the_path(tmp_path, capsys):
    empty_pdf = _touch(tmp_path / "qa" / "Bolatbek_QA.pdf")
    _touch(tmp_path / "fullstack" / "fs.pdf")

    def load_text(path):
        return "" if path == str(empty_pdf) else f"ТЕКСТ:{path}"

    CvLibrary(tmp_path, "/нет.pdf", load_text=load_text).for_role("qa")

    out = capsys.readouterr().out
    assert "CV пустой" in out
    assert str(empty_pdf) in out


def test_the_warning_prints_once_per_path_not_once_per_role_request(tmp_path, capsys):
    """Кэш по пути (test_two_roles_falling_back_to_the_same_file_read_it_once)
    должен точно так же гасить повторные предупреждения: 'ai' и 'mobile' оба
    без своей папки откатываются на один и тот же битый fullstack-файл, и
    жалоба на него не должна повторяться на каждую роль."""
    broken_pdf = _touch(tmp_path / "fullstack" / "fs.pdf")
    legacy = _touch(tmp_path.parent / "legacy.pdf")

    def load_text(path):
        if path == str(broken_pdf):
            raise ValueError("битый PDF")
        return f"ТЕКСТ:{path}"

    lib = CvLibrary(tmp_path, str(legacy), load_text=load_text)
    lib.for_role("ai")
    lib.for_role("mobile")

    out = capsys.readouterr().out
    assert out.count("CV не читается") == 1
