"""Живая ли сессия Jobicy. Судим по КУКАМ, а не по разметке.

Первая попытка судила по странице — «нет ссылки на /sign-in, значит мы внутри» —
и немедленно дала ложное «залогинен» прямо на самой странице входа: ссылки на
неё саму там, естественно, нет. Сохранилась гостевая сессия: три куки, одна
Cloudflare и две аналитики Matomo, ни одной авторизационной (замер 2026-09-11).

Разметка для этого не годится в принципе: на гостевой главной Jobicy стоит
`href="/dashboard-page"`, то есть «личный кабинет» виден и тому, кто не вошёл.
Кука — положительное доказательство, и именно её отсутствие обязано читаться как
«не вошёл». Та же дисциплина, что в domain/remoteok_session.py, только признак
надёжнее.
"""
from app.domain.jobicy_session import auth_cookie_names, is_logged_in


def _c(*names):
    return [{"name": n, "domain": "jobicy.com"} for n in names]


# Куки гостя, снятые живьём 2026-09-11 с сохранённой впустую сессии.
GUEST = _c("__cf_ob", "_pk_id.2.2360", "_pk_ses.2.2360")


def test_a_guest_has_no_session():
    assert is_logged_in(GUEST) is False


def test_no_cookies_at_all_is_no_session():
    assert is_logged_in([]) is False
    assert is_logged_in(None) is False


def test_a_wordpress_login_cookie_is_a_session():
    """Jobicy стоит на WordPress, а тот держит вход в `wordpress_logged_in_<хеш>`."""
    assert is_logged_in(GUEST + _c("wordpress_logged_in_4c1a2b")) is True


def test_the_wordpress_secure_cookie_counts_too():
    assert is_logged_in(_c("wordpress_sec_4c1a2b", "wordpress_logged_in_4c1a2b")) is True


def test_analytics_and_cdn_cookies_never_count():
    """Их выдают всем подряд, и принять их за вход — значит сохранить гостя."""
    noise = _c("__cf_bm", "_ga", "_gid", "_pk_ses.9", "PHPSESSID", "cf_clearance")
    assert is_logged_in(noise) is False


def test_the_names_we_saw_are_reportable():
    """Когда вход не опознан, человеку показывают, ЧТО реально пришло.

    Иначе следующий шаг — снова гадание об имени куки. Здесь же оно становится
    замером: имя видно в выводе команды.
    """
    assert auth_cookie_names(GUEST) == ["__cf_ob", "_pk_id.2.2360", "_pk_ses.2.2360"]
