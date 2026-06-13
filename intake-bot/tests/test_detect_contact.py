from app.domain.contact import Contact, detect_contact


def test_telegram_handle():
    c = detect_contact("Ищем backend. Пиши @ivan_hr по вакансии")
    assert c == Contact("telegram", "@ivan_hr")


def test_telegram_tme_link():
    c = detect_contact("Контакт: https://t.me/ivanhr спасибо")
    assert c.platform == "telegram"
    assert "t.me/ivanhr" in c.target


def test_email():
    c = detect_contact("Резюме на recruiter@company.com")
    assert c == Contact("email", "recruiter@company.com")


def test_plain_email_is_not_telegram():
    c = detect_contact("john@gmail.com")
    assert c.platform == "email"
    assert c.target == "john@gmail.com"


def test_linkedin():
    c = detect_contact("Профиль: linkedin.com/in/ivan-ivanov апплай тут")
    assert c.platform == "linkedin"
    assert "linkedin.com/in/ivan-ivanov" in c.target


def test_hh():
    c = detect_contact("Откликнуться: https://hh.ru/vacancy/12345?from=x")
    assert c.platform == "hh"
    assert "hh.ru/vacancy/12345" in c.target


def test_wellfound():
    c = detect_contact("Apply at https://wellfound.com/jobs/987-backend-engineer")
    assert c.platform == "wellfound"
    assert "wellfound.com/jobs/987-backend-engineer" in c.target


def test_priority_telegram_over_email():
    c = detect_contact("Пиши @ivan_hr или на boss@company.com")
    assert c.platform == "telegram"


def test_priority_email_over_linkedin():
    c = detect_contact("mail me@x.com or linkedin.com/in/me")
    assert c.platform == "email"


def test_none_when_no_contact():
    assert detect_contact("Просто описание вакансии без контактов") is None


def test_strips_trailing_punctuation_from_url():
    c = detect_contact("см. (linkedin.com/in/abc).")
    assert c.target.endswith("abc")
