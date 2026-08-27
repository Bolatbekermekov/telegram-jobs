"""Проводка: письмо и вложение обязаны прийти из одного и того же CV."""
from app.application.classify_role import classify_role
from app.application.cv_library import CvLibrary
from app.application.generate_message import GenerateMessage, generate_for
from app.domain.lead import Lead


class _Ai:
    def __init__(self):
        self.seen_cv = None

    def generate(self, cv_text, profile_text, vacancy_context, language=""):
        self.seen_cv = cv_text
        return "письмо"

    def generate_with_note(self, cv_text, profile_text, vacancy_context,
                           note_limit, language=""):
        self.seen_cv = cv_text
        return "письмо", "записка"


class _Chan:
    name = "linkedin"
    note_limit = 200


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF fake")
    return path


def _lead(vacancy):
    return Lead(row=2, lead_id="1", platform="linkedin", target="u",
                vacancy_context=vacancy, raw_text=vacancy, status="new")


def test_letter_and_attachment_come_from_the_same_variant(tmp_path):
    qa_pdf = _touch(tmp_path / "qa" / "Bolatbek_QA.pdf")
    _touch(tmp_path / "fullstack" / "fs.pdf")
    library = CvLibrary(tmp_path, "/нет.pdf", load_text=lambda p: f"ТЕКСТ:{p}")

    class _SaysQa:
        def classify(self, vacancy_context):
            return "qa"

    ai = _Ai()
    role = classify_role(_SaysQa(), "нужен тестировщик")
    variant = library.for_role(role)
    generate_for(GenerateMessage(ai, "ЗАПАСНОЕ", "p"), _lead("нужен тестировщик"),
                 _Chan(), variant.text)

    assert variant.pdf_path == str(qa_pdf)
    assert ai.seen_cv == f"ТЕКСТ:{qa_pdf}"


def test_a_classifier_failure_still_produces_a_usable_pair(tmp_path):
    """Сеть легла: лид всё равно уезжает, с запасным CV."""
    fs_pdf = _touch(tmp_path / "fullstack" / "fs.pdf")
    library = CvLibrary(tmp_path, "/нет.pdf", load_text=lambda p: f"ТЕКСТ:{p}")

    class _Boom:
        def classify(self, vacancy_context):
            raise RuntimeError("сеть легла")

    ai = _Ai()
    variant = library.for_role(classify_role(_Boom(), "любая вакансия"))
    body, note, err = generate_for(GenerateMessage(ai, "ЗАПАСНОЕ", "p"),
                                   _lead("любая вакансия"), _Chan(), variant.text)

    assert err is None
    assert variant.role == "fullstack"
    assert variant.pdf_path == str(fs_pdf)
    assert ai.seen_cv == f"ТЕКСТ:{fs_pdf}"
