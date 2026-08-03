"""Живая ли сессия RemoteOK — по самой странице, а не по наличию файла.

Файл сессии, сохранённый до того, как вход завершён, ничем не отличается от
рабочего: он есть, он читается, и всё ломается позже — на отклике, когда
RemoteOK уводит на /sign-up вместо формы работодателя. Ровно этой ошибкой
раньше отличались LinkedIn и Threads (см. infrastructure/linkedin_session.py).

Признак снят с живой страницы 2026-08-03: у разлогиненного в шапке
remoteok.com стоят href="/login" и href="/sign-up" (по 3 вхождения), а
href="/logout" не встречается ни разу.
"""
from app.domain.remoteok_session import is_logged_in

# Кусок настоящей шапки разлогиненного remoteok.com.
GUEST_HEADER = """
<nav>
  <a href="/remote-jobs">Remote Jobs</a>
  <a href="/workers">Hire remotely</a>
  <a href="/sign-up">Post a job</a>
  <a href="/login">Log in</a>
</nav>
""" + "<div>вакансии</div>" * 60


def test_a_guest_page_is_not_a_session():
    assert is_logged_in(GUEST_HEADER) is False


def test_a_logout_link_means_we_are_in():
    page = GUEST_HEADER.replace('<a href="/login">Log in</a>',
                                '<a href="/logout">Log out</a>')
    assert is_logged_in(page) is True


def test_a_page_without_a_login_offer_counts_as_logged_in():
    """Шапку могут перерисовать, и ссылки на выход в ней может не оказаться.
    Отсутствие приглашения войти — тоже свидетельство, и держаться только за
    /logout значит ломаться на первом же редизайне."""
    page = GUEST_HEADER.replace('<a href="/login">Log in</a>',
                                '<a href="/account">Мой профиль</a>')
    assert is_logged_in(page) is True


def test_nothing_to_judge_by_is_not_a_session():
    """Пустой ответ, таймаут или страница ошибки — не повод объявить вход
    успешным: это самый дешёвый способ сохранить сессию гостя."""
    for page in ("", None, "<html><body>Error 502</body></html>"):
        assert is_logged_in(page) is False, repr(page)[:40]


def test_the_signup_wall_is_not_a_session():
    """Страница /sign-up?user_type=worker — ровно то, куда RemoteOK уводит
    гостя с кнопки отклика. Принять её за вход значит сохранить сессию,
    которая гарантированно не сможет откликнуться."""
    page = ("<title>Create an account on Remote OK</title>"
            '<form><a href="/login">Log in</a></form>' + "<div>x</div>" * 200)
    assert is_logged_in(page) is False
