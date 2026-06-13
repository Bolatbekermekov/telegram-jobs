from app.application.generate_message import subject_for


def test_subject_uses_vacancy_first_line():
    assert subject_for("Backend Engineer at Acme\nRemote, Python") == \
        "Backend Engineer at Acme"


def test_subject_falls_back_when_empty():
    assert subject_for("") == "Заявка на вакансию"


def test_subject_is_trimmed_to_one_line_and_capped():
    long = "x" * 200
    s = subject_for(long)
    assert "\n" not in s
    assert len(s) <= 120
